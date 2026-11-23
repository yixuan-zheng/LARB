"""Fixed histories only. Uses local endpoints and never runs an orchestrator episode."""

import json
import os
import time
from pathlib import Path

from litellm import completion
from tau2.data_model.message import AssistantMessage, UserMessage
from tau2.data_model.tasks import UserScenario
from tau2.user.user_simulator import UserSimulator
from tokenizers import Tokenizer

ROOT = Path(os.environ["TAU_ROOT"])
OUT = Path(os.environ["TAU_OUT"])
KEY = (OUT / "key").read_text().strip()

CASES = {
    "airline": {
        "0": ("What is your reservation code?", "I can cancel it, but you will receive no refund. Shall I proceed?"),
        "1": ("Which route are you asking about?", "I cannot cancel this reservation for a refund. What would you like to do?"),
        "2": ("What is the reservation number of the delayed flight?", "Our records show two travelers, and we can change that reservation. Do you want me to?"),
    },
    "retail": {
        "0": ("What is your order number?", "The clicky keyboard is available only without backlighting. Do you want that one?"),
        "1": ("What is your order number?", "The clicky keyboard is available only without backlighting. Should we exchange both items?"),
        "2": ("May I have your email address?", "I listed the T-shirt options but have not started a return. Is there anything else?"),
    },
}

# Prior turns are fixed and identical across the two simulator checkpoints.
HISTORIES = {
    ("airline", "0"): ("I need to cancel reservation EHGLP3.",
                       "I can look into that. What would make cancellation acceptable?",
                       "I only want to cancel if I get a refund."),
    ("airline", "1"): ("I want to cancel my Philadelphia to LaGuardia reservation.",
                       "Let me check its cancellation policy.",
                       "A representative said you could help. I only want to cancel with a refund."),
    ("airline", "2"): ("My most recent flight was delayed.",
                       "Can you identify the delayed booking?",
                       "It was the last reservation I made. I thought there were three travelers."),
    ("retail", "0"): ("I want to exchange my keyboard and thermostat.",
                      "What features do you need?",
                      "Clicky switches and a Google Home thermostat. I can accept a keyboard with no backlighting."),
    ("retail", "1"): ("I want to exchange my keyboard and thermostat.",
                      "What should we do if your exact keyboard is unavailable?",
                      "If you cannot match the full-size, clicky, RGB keyboard, exchange only the thermostat."),
    ("retail", "2"): ("I want to know the T-shirt options and return three items.",
                      "Which items should I look up?",
                      "The cleaner, headphones, and smart watch. Please handle all three returns."),
}

def log(kind, **row):
    with (OUT / f"{kind}.jsonl").open("a") as stream:
        stream.write(json.dumps(row) + "\n")

def ask(model, url, messages, **kwargs):
    return completion(model=f"openai/{model}", api_base=url, api_key=KEY,
                      messages=messages, timeout=180, num_retries=0, **kwargs)

def customer(url, model="customer"):
    for domain, cases in CASES.items():
        path = ROOT / f"data/tau2/domains/{domain}/tasks.json"
        tasks = {str(row["id"]): row for row in json.loads(path.read_text())}
        for task_id, prompts in cases.items():
            scenario = UserScenario.model_validate(tasks[task_id]["user_scenario"])
            user = UserSimulator(f"openai/{model}", instructions=str(scenario),
                llm_args=dict(api_base=url, api_key=KEY, temperature=0, max_tokens=256,
                              timeout=90, num_retries=0))
            for index, prompt in enumerate(prompts):
                started = time.monotonic()
                try:
                    history = []
                    if index == 1:
                        first, reply, last = HISTORIES[domain, task_id]
                        history = [UserMessage(role="user", content=first),
                                   AssistantMessage(role="assistant", content=reply),
                                   UserMessage(role="user", content=last)]
                    result, _ = user.generate_next_message(
                        AssistantMessage(role="assistant", content=prompt), user.get_init_state(history))
                    log(model, domain=domain, task=task_id, fixture=index, prompt=prompt,
                        response=result.model_dump(mode="json"), seconds=time.monotonic()-started)
                except Exception as exc:
                    log(model, domain=domain, task=task_id, fixture=index,
                        error_type=type(exc).__name__, seconds=time.monotonic()-started)

TOOL = {"type":"function","function":{"name":"lookup_order",
    "description":"Read a simulated order by identifier",
    "parameters":{"type":"object","properties":{"order_id":{"type":"string"}},
                  "required":["order_id"],"additionalProperties":False}}}

def agent(url):
    tokenizer = Tokenizer.from_file(str(Path(os.environ["AGENT_MODEL"]) / "tokenizer.json"))
    for cap in (512, 2048):
        for fixture, question in {
            "plain": "Reply with one sentence confirming that you can help.",
            "tool": "Call lookup_order for order W2378156 now.",
            "stress": ("Think carefully about at least 100 possible checks before answering. "
                       "Your only action after thinking must be calling lookup_order for order W2378156."),
        }.items():
            messages = [{"role":"user","content":question}]
            for turn in range(2 if fixture != "plain" else 1):
                key = f"tau--{cap}-{fixture}-{turn}"
                started = time.monotonic()
                try:
                    response = ask("agent", url, messages, temperature=0.6, seed=17, top_p=0.95,
                        tools=[TOOL], tool_choice="auto", max_tokens=cap+1026,
                        extra_body={"vllm_xargs":{"reasoning_cap":cap,"fixture_id":key,
                            "hold_until_cap": int(cap == 2048 and fixture == "stress" and turn == 0),
                            "tool_start_id": tokenizer.token_to_id("<tool_call>"),
                            "early_eos_id": tokenizer.token_to_id("<|endoftext|>"),
                            "close_id":tokenizer.token_to_id("</think>"),
                            "eos_id":tokenizer.token_to_id("<|im_end|>")}})
                    choice = response.choices[0]
                    msg = choice.message
                    tool_calls = msg.tool_calls or []
                    valid = (len(tool_calls) == 1 and bool(tool_calls[0].id)
                        and tool_calls[0].function.name == "lookup_order"
                        and json.loads(tool_calls[0].function.arguments) == {"order_id":"W2378156"})
                    log("agent", key=key, budget=cap, seconds=time.monotonic()-started,
                        valid_call=valid, finish=choice.finish_reason,
                        response=msg.model_dump(exclude_none=True), usage=response.usage.model_dump())
                    if not valid or turn != 0:
                        break
                    messages.extend([
                        {"role":"assistant","tool_calls":[tool_calls[0].model_dump()]},
                        {"role":"tool","tool_call_id":tool_calls[0].id,
                         "content":'{"order_id":"W2378156","status":"delivered"}'},
                        {"role":"user","content":"Tell me the status in one sentence without calling again."},
                    ])
                except Exception as exc:
                    log("agent", key=key, budget=cap, error_type=type(exc).__name__)
                    break

if __name__ == "__main__":
    import sys
    if sys.argv[1] == "agent":
        agent("http://127.0.0.1:18783/v1")
    else:
        customer(Path(sys.argv[2]).read_text().strip(), model=sys.argv[1])
