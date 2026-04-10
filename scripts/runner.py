#!/usr/bin/env python3
import argparse
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MIN_EMPTY_CHARS = 80
MIN_SUBSTANTIVE_CHARS = 250
QUALITY_KEYWORDS = ["recommend", "recommendation", "option", "options", "tradeoff", "trade-off", "risk", "risks"]
MODE_PROMPTS = {
    "debate": [
        "Produce 2-4 options.",
        "Argue against the leading option at least once.",
        "Identify what would change the recommendation.",
    ],
    "architecture": [
        "Define components, interfaces, states, and failure modes.",
        "Prefer explicit operating rules over vague principles.",
        "End with a recommended design.",
    ],
    "coding": [
        "Debate the approach before implementation.",
        "Call out brittle assumptions and fake-good test strategies.",
        "Recommend verification that the host agent can check independently.",
    ],
    "critique": [
        "Attack the current answer first.",
        "Identify omissions, contradictions, and hidden risks.",
        "Only then produce a repaired recommendation.",
    ],
}
FOLLOW_UP_PROMPT = "Attack your own recommendation. What is the strongest case against it?"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def slug_ts():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')


def load_state(run_dir: Path) -> dict:
    return json.loads(read_text(run_dir / 'state.json'))


def save_state(run_dir: Path, state: dict) -> None:
    write_text(run_dir / 'state.json', json.dumps(state, ensure_ascii=False, indent=2) + '\n')


def log_event(run_dir: Path, state: dict, event: str, detail: dict) -> None:
    append_jsonl(run_dir / 'run.jsonl', {
        'ts': now_iso(),
        'run_id': state['run_id'],
        'event': event,
        'step': state['step'],
        'detail': detail,
    })


def detect_acp_format(path: Path) -> str:
    with path.open('r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                return 'text'
            if isinstance(obj, dict) and any(k in obj for k in ('kind', 'type', 'phase', 'delta')):
                return 'jsonl'
            return 'text'
    return 'text'


def extract_from_text(path: Path) -> tuple[str, str]:
    text = read_text(path)
    if len(text.strip()) < MIN_EMPTY_CHARS:
        return 'empty', text
    return 'success', text


def extract_from_acp_log(path: Path) -> tuple[str, str]:
    chunks = []
    saw_complete = False
    saw_stall = False
    saw_error = False
    error_text = ''

    with path.open('r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = str(obj.get('kind') or obj.get('type') or '').lower()
            phase = str(obj.get('phase') or obj.get('data', {}).get('phase') or '').lower()
            text = obj.get('delta') or obj.get('text') or obj.get('content') or ''

            if kind in {'error', 'failure'}:
                saw_error = True
                error_text = text or obj.get('message', '') or error_text
                continue

            if kind == 'system_event':
                lowered = str(text).lower()
                if 'produced no output' in lowered or 'may be waiting for interactive input' in lowered:
                    saw_stall = True
                if 'run completed' in lowered:
                    saw_complete = True
                continue

            if kind == 'lifecycle' and phase == 'end':
                saw_complete = True
                continue

            if kind in {'assistant_delta', 'assistant', 'result'} and text:
                chunks.append(str(text))
                continue

            role = str(obj.get('role') or '').lower()
            if role == 'assistant' and text:
                chunks.append(str(text))

    combined = ''.join(chunks).strip()
    verdict = evaluate_text(combined)[0] if combined else 'empty'

    if saw_error:
        return 'error', error_text or combined
    if saw_stall and verdict != 'sufficient':
        return 'stale', combined
    if saw_complete:
        if verdict == 'empty':
            return 'empty', combined
        return 'success', combined
    if combined:
        return 'success', combined
    return 'stale', ''


def apply_acp_result(run_dir: Path, state: dict, status: str, response_text: Optional[str]) -> tuple[str, dict]:
    state['attempt_acp'] += 1
    state['step'] = 'ACP_EVAL'
    detail = {'status': status}

    if response_text is not None and response_text.strip():
        dst = run_dir / f'acp-response-{state["attempt_acp"]}.txt'
        write_text(dst, response_text + ('\n' if not response_text.endswith('\n') else ''))
        state['responses'].append(str(dst))
        state['last_response_path'] = str(dst)
        verdict, meta = evaluate_text(response_text)
        state['last_verdict'] = verdict
        detail.update(meta)
        detail['response_file'] = str(dst)
    else:
        verdict = 'empty' if status == 'success' else status
        state['last_verdict'] = verdict

    if status != 'success':
        state['step'] = 'CLI_CALL'
        state['rail_used'] = 'acp'
        next_step = 'cli_call'
    else:
        state['rail_used'] = 'acp'
        if state['last_verdict'] == 'sufficient':
            state['step'] = 'DONE'
            state['done'] = True
            next_step = 'done'
        elif state['follow_up_budget'] > 0:
            state['step'] = 'FOLLOW_UP'
            next_step = 'follow_up'
        else:
            state['step'] = 'CLI_CALL'
            next_step = 'cli_call'

    save_state(run_dir, state)
    log_event(run_dir, state, 'acp_result', detail | {'next_step': next_step})
    return next_step, detail


def evaluate_text(text: str) -> tuple[str, dict]:
    stripped = text.strip()
    lowered = stripped.lower()
    if len(stripped) < MIN_EMPTY_CHARS:
        return 'empty', {'chars': len(stripped), 'keyword_hits': 0}
    keyword_hits = sum(1 for kw in QUALITY_KEYWORDS if kw in lowered)
    if len(stripped) >= MIN_SUBSTANTIVE_CHARS and keyword_hits >= 2:
        return 'sufficient', {'chars': len(stripped), 'keyword_hits': keyword_hits}
    return 'weak', {'chars': len(stripped), 'keyword_hits': keyword_hits}


def build_base_prompt(task: str, mode: str) -> str:
    bullets = '\n'.join(f'- {line}' for line in MODE_PROMPTS[mode])
    return (
        f"Ultrathink. Pressure-test this in {mode} mode.\n\n"
        f"Task:\n{task.strip()}\n\n"
        f"What I need from you:\n"
        f"- options\n- tradeoffs\n- risks\n- recommendation\n\n"
        f"Mode rules:\n{bullets}\n\n"
        f"Rules:\n"
        f"- do not be agreeable by default\n"
        f"- attack the strongest-looking answer at least once\n"
        f"- be concrete, not hand-wavy\n"
        f"- if something is uncertain, say what would resolve it\n"
    )


def build_follow_up_prompt(task: str, prior_response: str) -> str:
    return (
        f"We are pressure-testing this further.\n\n"
        f"Original task:\n{task.strip()}\n\n"
        f"Prior answer:\n{prior_response.strip()}\n\n"
        f"Follow-up:\n{FOLLOW_UP_PROMPT}\n"
    )


def call_local_claude(skill_dir: Path, workdir: Path, prompt_file: Path, timeout_seconds: int = 180) -> tuple[str, str, int]:
    cmd = [str(skill_dir / 'scripts' / 'local-claude-fallback.sh'), str(workdir), str(prompt_file)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if proc.returncode != 0:
            return 'error', stderr or stdout, proc.returncode
        return 'success', stdout, 0
    except subprocess.TimeoutExpired:
        return 'timeout', '', 124


def get_skill_dir(run_dir: Path, state: dict) -> Path:
    stored = state.get('skill_dir')
    if stored:
        return Path(stored)
    # Backward-compatible fallback for runs created before skill_dir was persisted in state.
    return run_dir.parents[2]


def init_run(args):
    skill_dir = Path(args.skill_dir).resolve()
    task_file = Path(args.task_file).resolve()
    task = read_text(task_file)
    run_id = f"{slug_ts()}-{uuid.uuid4().hex[:8]}"
    run_dir = skill_dir / 'state' / 'runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    mode = args.mode
    prompt = build_base_prompt(task, mode)
    write_text(run_dir / 'task.txt', task)
    write_text(run_dir / 'base-prompt.txt', prompt)
    state = {
        'run_id': run_id,
        'skill_dir': str(skill_dir),
        'step': 'ACP_CALL' if args.prefer_rail == 'acp' else 'CLI_CALL',
        'mode': mode,
        'prefer_rail': args.prefer_rail,
        'attempt_acp': 0,
        'attempt_cli': 0,
        'follow_up_budget': 1,
        'responses': [],
        'last_response_path': None,
        'last_verdict': None,
        'rail_used': None,
        'done': False,
        'error': None,
    }
    save_state(run_dir, state)
    log_event(run_dir, state, 'init', {'mode': mode, 'prefer_rail': args.prefer_rail, 'task_chars': len(task)})
    payload = {
        'run_id': run_id,
        'run_dir': str(run_dir),
        'mode': mode,
        'next_step': state['step'].lower(),
        'base_prompt_file': str(run_dir / 'base-prompt.txt'),
        'task_file': str(run_dir / 'task.txt'),
    }
    print(json.dumps(payload, ensure_ascii=False))


def mark_acp(args):
    run_dir = Path(args.run_dir).resolve()
    state = load_state(run_dir)
    response_text = None
    if args.response_file:
        response_text = read_text(Path(args.response_file).resolve())
    next_step, _detail = apply_acp_result(run_dir, state, args.status, response_text)
    print(json.dumps({'run_dir': str(run_dir), 'next_step': next_step, 'last_verdict': state['last_verdict']}, ensure_ascii=False))


def ingest_acp(args):
    run_dir = Path(args.run_dir).resolve()
    state = load_state(run_dir)
    src = Path(args.file).resolve()

    if not src.exists():
        inferred_status, response_text = 'error', ''
    elif src.stat().st_size == 0:
        inferred_status, response_text = 'empty', ''
    elif detect_acp_format(src) == 'jsonl':
        inferred_status, response_text = extract_from_acp_log(src)
    else:
        inferred_status, response_text = extract_from_text(src)

    next_step, _detail = apply_acp_result(run_dir, state, inferred_status, response_text)
    print(json.dumps({
        'run_dir': str(run_dir),
        'next_step': next_step,
        'last_verdict': state['last_verdict'],
        'inferred_status': inferred_status,
        'last_response_path': state['last_response_path'],
    }, ensure_ascii=False))


def run_cli_common(run_dir: Path, state: dict, prompt_text: str, prompt_name: str):
    prompt_file = run_dir / prompt_name
    write_text(prompt_file, prompt_text)
    status, output, exit_code = call_local_claude(get_skill_dir(run_dir, state), Path.cwd(), prompt_file)
    response_file = run_dir / f'cli-response-{state["attempt_cli"]}.txt'
    if output:
        write_text(response_file, output + ('\n' if not output.endswith('\n') else ''))
        state['responses'].append(str(response_file))
        state['last_response_path'] = str(response_file)
    verdict, meta = evaluate_text(output) if status == 'success' else (status, {'chars': 0, 'keyword_hits': 0})
    state['last_verdict'] = verdict
    detail = {'status': status, 'exit_code': exit_code, 'response_file': str(response_file) if output else None} | meta
    return status, output, verdict, detail


def run_cli(args):
    run_dir = Path(args.run_dir).resolve()
    state = load_state(run_dir)
    state['attempt_cli'] += 1
    state['step'] = 'CLI_CALL'
    task = read_text(run_dir / 'task.txt')
    prompt_text = build_base_prompt(task, state['mode'])
    status, _output, verdict, detail = run_cli_common(run_dir, state, prompt_text, f'cli-prompt-{state["attempt_cli"]}.txt')
    if status == 'success' and verdict == 'sufficient':
        state['step'] = 'DONE'
        state['done'] = True
        next_step = 'done'
    elif status == 'success' and state['follow_up_budget'] > 0:
        state['step'] = 'FOLLOW_UP'
        next_step = 'follow_up'
    else:
        state['step'] = 'FAILED'
        state['done'] = True
        state['error'] = f'cli_{status}'
        next_step = 'failed'
    state['rail_used'] = 'cli'
    save_state(run_dir, state)
    log_event(run_dir, state, 'cli_result', detail | {'next_step': next_step})
    print(json.dumps({'run_dir': str(run_dir), 'next_step': next_step, 'last_verdict': state['last_verdict'], 'last_response_path': state['last_response_path']}, ensure_ascii=False))


def follow_up(args):
    run_dir = Path(args.run_dir).resolve()
    state = load_state(run_dir)
    if state['follow_up_budget'] <= 0:
        print(json.dumps({'run_dir': str(run_dir), 'next_step': 'done', 'reason': 'no_budget'}, ensure_ascii=False))
        return
    state['follow_up_budget'] -= 1
    state['attempt_cli'] += 1
    state['step'] = 'FOLLOW_UP'
    task = read_text(run_dir / 'task.txt')
    prior_response = read_text(Path(state['last_response_path'])) if state['last_response_path'] else ''
    prompt_text = build_follow_up_prompt(task, prior_response)
    status, _output, verdict, detail = run_cli_common(run_dir, state, prompt_text, f'follow-up-prompt-{state["attempt_cli"]}.txt')
    if status == 'success' and verdict == 'sufficient':
        state['step'] = 'DONE'
        state['done'] = True
        next_step = 'done'
    else:
        state['step'] = 'FAILED'
        state['done'] = True
        state['error'] = f'follow_up_{status}_{verdict}'
        next_step = 'failed'
    state['rail_used'] = 'cli'
    save_state(run_dir, state)
    log_event(run_dir, state, 'follow_up_result', detail | {'next_step': next_step, 'remaining_budget': state['follow_up_budget']})
    print(json.dumps({'run_dir': str(run_dir), 'next_step': next_step, 'last_verdict': state['last_verdict'], 'last_response_path': state['last_response_path']}, ensure_ascii=False))


def status_cmd(args):
    run_dir = Path(args.run_dir).resolve()
    state = load_state(run_dir)
    print(json.dumps(state, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description='Deterministic runner for the whip-claude OpenClaw skill.'
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('init')
    p.add_argument('--skill-dir', required=True)
    p.add_argument('--task-file', required=True)
    p.add_argument('--mode', choices=sorted(MODE_PROMPTS.keys()), required=True)
    p.add_argument('--prefer-rail', choices=['acp', 'cli'], default='acp')
    p.set_defaults(func=init_run)

    p = sub.add_parser('mark-acp')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--status', choices=['success', 'stale', 'error', 'empty'], required=True)
    p.add_argument('--response-file')
    p.set_defaults(func=mark_acp)

    p = sub.add_parser('ingest-acp')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--file', required=True)
    p.set_defaults(func=ingest_acp)

    p = sub.add_parser('run-cli')
    p.add_argument('--run-dir', required=True)
    p.set_defaults(func=run_cli)

    p = sub.add_parser('follow-up')
    p.add_argument('--run-dir', required=True)
    p.set_defaults(func=follow_up)

    p = sub.add_parser('status')
    p.add_argument('--run-dir', required=True)
    p.set_defaults(func=status_cmd)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
