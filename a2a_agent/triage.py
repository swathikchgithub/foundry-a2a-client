"""
Ticket triage logic for the local A2A agent.

Deliberately a dependency-free keyword classifier so the whole A2A round trip
can be run on a laptop with no GPU. The interface is a single function,
`triage(text) -> TriageResult`; swap its body for a call to a real model
(e.g. the LoRA TicketSense classifier) later without touching the server.
"""

import re
from dataclasses import dataclass

# Order matters: the first category with the highest score wins ties, so the
# more specific categories (phishing, password) come before the broad ones.
CATEGORY_KEYWORDS = {
    "Security_Phishing": ["phish", "suspicious", "fake", "scam", "malware", "virus",
                          "spoof", "clicked a link", "attachment", "ransomware"],
    "Password_Reset": ["password", "reset", "expired", "locked out", "forgot",
                       "mfa", "2fa", "authenticator"],
    "Access_Account": ["access", "permission", "denied", "unauthorized", "role",
                       "account", "onboard", "provision", "sharepoint"],
    "Email": ["email", "outlook", "inbox", "mailbox", "calendar", "distribution list"],
    "Printer": ["printer", "print", "toner", "paper jam", "scanner"],
    "Network": ["wifi", "wi-fi", "vpn", "internet", "network", "ethernet",
                "dns", "disconnect", "latency"],
    "Hardware": ["laptop", "monitor", "keyboard", "mouse", "battery", "screen",
                 "dock", "charger", "headset", "broken"],
    "Software": ["install", "crash", "app", "update", "license", "error",
                 "jira", "teams", "excel", "slack", "freez"],
}

ROUTING = {
    "Security_Phishing": ("P1", "Security Operations"),
    "Password_Reset": ("P3", "Service Desk"),
    "Access_Account": ("P3", "Identity & Access"),
    "Email": ("P3", "Messaging"),
    "Printer": ("P4", "Desktop Support"),
    "Network": ("P2", "Network Operations"),
    "Hardware": ("P3", "Desktop Support"),
    "Software": ("P3", "Application Support"),
}

URGENT_WORDS = ["urgent", "asap", "blocking", "down", "outage", "everyone", "cannot work"]


@dataclass
class TriageResult:
    category: str
    priority: str
    team: str
    confidence: float
    matched: list[str]

    def to_text(self) -> str:
        matched = ", ".join(self.matched) if self.matched else "none"
        return (
            f"Category: {self.category}\n"
            f"Priority: {self.priority}\n"
            f"Route to: {self.team}\n"
            f"Confidence: {self.confidence:.2f}\n"
            f"Matched keywords: {matched}"
        )


def triage(text: str) -> TriageResult:
    lowered = text.lower()
    scores: dict[str, list[str]] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = [k for k in keywords if k in lowered]
        if hits:
            scores[category] = hits

    if not scores:
        return TriageResult("Software", "P4", "Service Desk", 0.2, [])

    category = max(scores, key=lambda c: len(scores[c]))
    total_hits = sum(len(h) for h in scores.values())
    confidence = round(len(scores[category]) / total_hits, 2)

    priority, team = ROUTING[category]
    if any(re.search(rf"\b{w}\b", lowered) for w in URGENT_WORDS) and priority != "P1":
        priority = f"P{int(priority[1]) - 1}"

    return TriageResult(category, priority, team, confidence, scores[category])
