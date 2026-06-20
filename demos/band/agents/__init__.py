from .audit_agent import AuditAgent, PROMPT as AUDIT_PROMPT
from .report_agent import ReportAgent, PROMPT as REPORT_PROMPT
from .research_agent import ResearchAgent, PROMPT as RESEARCH_PROMPT
from .verifier_agent import VerifierAgent, PROMPT as VERIFIER_PROMPT


AGENT_PROMPTS = {
    "ResearchAgent": RESEARCH_PROMPT,
    "ReportAgent": REPORT_PROMPT,
    "VerifierAgent": VERIFIER_PROMPT,
    "AuditAgent": AUDIT_PROMPT,
}

__all__ = [
    "AGENT_PROMPTS",
    "AuditAgent",
    "ReportAgent",
    "ResearchAgent",
    "VerifierAgent",
]

