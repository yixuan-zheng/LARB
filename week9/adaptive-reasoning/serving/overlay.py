"""Build the isolated step-24 HTTP server from the validated replay server."""
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()


def replace(old, new):
    global text
    if text.count(old) != 1:
        raise ValueError(f"Unexpected server source for {old!r}")
    text = text.replace(old, new)


replace("from larb_scaled import config", """from larb_scaled import config
from routed_contract import choose, prefixes, ARMS
from vllm.lora.request import LoRARequest""")
replace('RENDERED_PROMPTS = {}','RENDERED_PROMPTS = {}\nADAPTER = None')
replace('if body.get("arm") not in PROTOCOL["policy"]["arms"]:','if body.get("arm") not in ARMS:')
start = text.index('    if request_class == "filler":\n        budget = ')
end = text.index('    if len(prompt_ids) + max_tokens', start)
text = text[:start] + """    mode, budget, live = choose(ARM, question, len(waiting) >= threshold)
    if request_class == "filler":
        mode, budget, live = 2, 256, False
    prompt_start = time.monotonic()
    prompt_ids = RENDERED_PROMPTS[question_id][mode]
    rendered = question["prompt"]
    prompt_end = time.monotonic()
    max_tokens = (PROTOCOL["budgets"]["long"] + len(CONTRACT.cue) + CONTRACT.answer_cap + 2
                  if mode else CONTRACT.answer_cap)
""" + text[end:]
replace('key=key, policy=ARM, budget=budget, cue=list(CONTRACT.cue),','key=key, policy="live" if live else "fixed", budget=budget, cue=list(CONTRACT.cue),')
replace('extra_args={"larb": extra},','extra_args={"larb": extra} if mode else None,')
replace('                                                request_id=key):','                                                request_id=key, lora_request=ADAPTER):')
replace('persisted = await read_request_state(key)','persisted = await read_request_state(key) if mode else {}')
replace('initial_budget=budget, final_budget=final_budget,','initial_budget=budget, final_budget=final_budget, mode=mode,')
replace('prompt_token_ids=prompt_ids, raw_output=text, token_ids=token_ids,','prompt_token_ids=prompt_ids, raw_output=text, token_ids=token_ids,\n                answer_only=not mode,')
replace('global TOKENIZER, CONTRACT, SAMPLING_PARAMS','global TOKENIZER, CONTRACT, SAMPLING_PARAMS, ADAPTER')
replace('    if os.environ.get("LARB_PRETOKENIZE_FROZEN") == "1":\n        RENDERED_PROMPTS.update({qid: render_prompt(question) for qid, question in QUESTIONS.items()})',
        '    RENDERED_PROMPTS.update({qid: prefixes(TOKENIZER, question["problem"]) for qid, question in QUESTIONS.items()})\n'
        '    ADAPTER = LoRARequest("step24", 1, os.environ["LARB_ADAPTER"])')
replace('        generation_config="vllm",','        generation_config="vllm", enable_lora=True, max_lora_rank=16,')
replace('                log_level="warning")','                log_level="warning", timeout_keep_alive=180)')
path.write_text(text)

path = path.with_name("analysis.py")
text = path.read_text()
replace('    close_id = raw.get("close_id")','    close_id = raw.get("close_id")\n    if raw.get("answer_only"):\n        token_ids = [close_id, *token_ids] if token_ids else []')
path.write_text(text)
