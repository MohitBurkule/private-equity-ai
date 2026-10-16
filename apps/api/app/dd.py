"""DD request list: what the deal team asked for, what arrived, what is still missing."""
from __future__ import annotations

TEMPLATE: dict[str, list[str]] = {
    "financial": ["Audited financial statements, last 3 years", "Monthly management accounts, last 24 months",
                  "Quality of earnings report", "Budget and 3-year forecast model",
                  "Debt schedule and facility agreements", "Capex history and plan",
                  "Net working capital by month, last 24 months"],
    "commercial": ["Customer list with revenue by customer, last 3 years", "Top 10 customer contracts",
                   "Market study or commercial due diligence report", "Pricing history and policy",
                   "Churn and retention data"],
    "legal": ["Corporate structure chart", "Material contracts and change-of-control clauses",
              "Litigation and claims register", "IP ownership and licences", "Employment contracts for key staff"],
    "tax": ["Tax returns, last 3 years", "Open tax audits and correspondence", "Transfer pricing documentation"],
    "hr": ["Organisation chart and headcount by function", "Pension and benefit obligations",
           "Key-person and management incentive arrangements"],
    "it_esg": ["IT systems overview and security audits", "Data protection compliance records",
               "Environmental permits and ESG policies"],
}
STATUSES = ("open", "received", "waived")
