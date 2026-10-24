from netdiag.prompts import SYSTEM_PROMPT


def test_prompt_keeps_its_guardrails():
    for phrase in ("ONLY numbers", "NO remediation", "NOT a DNS-resolution problem",
                   "Operation not permitted", "ALWAYS call ping_endpoints"):
        assert phrase in SYSTEM_PROMPT
