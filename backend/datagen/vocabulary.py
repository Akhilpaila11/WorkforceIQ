"""Author-written role and skill taxonomy (fully synthetic; no external data source)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.enums import RoleFamily, SkillCategory

C = SkillCategory


@dataclass(frozen=True)
class RoleDef:
    code: str
    name: str
    family: RoleFamily
    categories: tuple[SkillCategory, ...]  # first = primary skill category
    weight: float  # share of headcount


ROLES: tuple[RoleDef, ...] = (
    RoleDef(
        "BACKEND_ENGINEER",
        "Backend Engineer",
        RoleFamily.ENGINEERING,
        (C.PROGRAMMING, C.ARCHITECTURE, C.DEVOPS),
        14,
    ),
    RoleDef(
        "FRONTEND_ENGINEER",
        "Frontend Engineer",
        RoleFamily.ENGINEERING,
        (C.PROGRAMMING, C.DESIGN, C.TESTING),
        10,
    ),
    RoleDef(
        "DATA_ENGINEER",
        "Data Engineer",
        RoleFamily.DATA,
        (C.DATA_ANALYTICS, C.PROGRAMMING, C.CLOUD),
        9,
    ),
    RoleDef(
        "QA_ENGINEER",
        "QA Engineer",
        RoleFamily.QUALITY,
        (C.TESTING, C.PROGRAMMING, C.MANAGEMENT),
        8,
    ),
    RoleDef(
        "CLOUD_ENGINEER",
        "Cloud Engineer",
        RoleFamily.CLOUD_INFRA,
        (C.CLOUD, C.DEVOPS, C.SECURITY),
        7,
    ),
    RoleDef(
        "DATA_SCIENTIST",
        "Data Scientist",
        RoleFamily.DATA,
        (C.DATA_ANALYTICS, C.PROGRAMMING, C.DOMAIN),
        5,
    ),
    RoleDef("UX_DESIGNER", "UX Designer", RoleFamily.DESIGN, (C.DESIGN, C.MANAGEMENT, C.DOMAIN), 5),
    RoleDef(
        "PRODUCT_OWNER", "Product Owner", RoleFamily.PRODUCT, (C.MANAGEMENT, C.DOMAIN, C.DESIGN), 5
    ),
    RoleDef(
        "PROJECT_MANAGER",
        "Project Manager",
        RoleFamily.DELIVERY,
        (C.MANAGEMENT, C.DOMAIN, C.ARCHITECTURE),
        6,
    ),
    RoleDef(
        "SECURITY_ENGINEER",
        "Security Engineer",
        RoleFamily.SECURITY,
        (C.SECURITY, C.CLOUD, C.DEVOPS),
        4,
    ),
    RoleDef(
        "FULLSTACK_ENGINEER",
        "Full-stack Engineer",
        RoleFamily.ENGINEERING,
        (C.PROGRAMMING, C.ARCHITECTURE, C.TESTING),
        8,
    ),
    RoleDef(
        "MOBILE_ENGINEER",
        "Mobile Engineer",
        RoleFamily.ENGINEERING,
        (C.PROGRAMMING, C.DESIGN, C.TESTING),
        4,
    ),
    RoleDef(
        "DEVOPS_ENGINEER",
        "DevOps Engineer",
        RoleFamily.CLOUD_INFRA,
        (C.DEVOPS, C.CLOUD, C.PROGRAMMING),
        5,
    ),
    RoleDef(
        "SITE_RELIABILITY_ENGINEER",
        "Site Reliability Engineer",
        RoleFamily.CLOUD_INFRA,
        (C.DEVOPS, C.CLOUD, C.ARCHITECTURE),
        3,
    ),
    RoleDef(
        "DATA_ANALYST",
        "Data Analyst",
        RoleFamily.DATA,
        (C.DATA_ANALYTICS, C.DOMAIN, C.MANAGEMENT),
        5,
    ),
    RoleDef(
        "ML_ENGINEER",
        "Machine Learning Engineer",
        RoleFamily.DATA,
        (C.DATA_ANALYTICS, C.PROGRAMMING, C.CLOUD),
        3,
    ),
    RoleDef(
        "TEST_AUTOMATION_ENGINEER",
        "Test Automation Engineer",
        RoleFamily.QUALITY,
        (C.TESTING, C.PROGRAMMING, C.DEVOPS),
        4,
    ),
    RoleDef(
        "UI_DESIGNER", "UI Designer", RoleFamily.DESIGN, (C.DESIGN, C.PROGRAMMING, C.MANAGEMENT), 3
    ),
    RoleDef(
        "BUSINESS_ANALYST",
        "Business Analyst",
        RoleFamily.PRODUCT,
        (C.MANAGEMENT, C.DOMAIN, C.DATA_ANALYTICS),
        5,
    ),
    RoleDef(
        "SCRUM_MASTER", "Scrum Master", RoleFamily.DELIVERY, (C.MANAGEMENT, C.DOMAIN, C.TESTING), 3
    ),
    RoleDef(
        "DELIVERY_MANAGER",
        "Delivery Manager",
        RoleFamily.DELIVERY,
        (C.MANAGEMENT, C.DOMAIN, C.ARCHITECTURE),
        3,
    ),
    RoleDef(
        "SOLUTION_ARCHITECT",
        "Solution Architect",
        RoleFamily.ENGINEERING,
        (C.ARCHITECTURE, C.CLOUD, C.PROGRAMMING),
        3,
    ),
    RoleDef(
        "SECURITY_ANALYST",
        "Security Analyst",
        RoleFamily.SECURITY,
        (C.SECURITY, C.MANAGEMENT, C.DOMAIN),
        2,
    ),
    RoleDef(
        "DATABASE_ADMINISTRATOR",
        "Database Administrator",
        RoleFamily.DATA,
        (C.DATA_ANALYTICS, C.DEVOPS, C.CLOUD),
        2,
    ),
)
ROLE_BY_CODE = {r.code: r for r in ROLES}

_BASE_SKILLS: dict[SkillCategory, tuple[str, ...]] = {
    C.PROGRAMMING: (
        "Python",
        "Java",
        "JavaScript",
        "TypeScript",
        "C#",
        "Go",
        "Kotlin",
        "Swift",
        "Rust",
        "C++",
        "PHP",
        "Ruby",
        "Scala",
        "React",
        "Angular",
        "Vue.js",
        "Node.js",
        "Spring Boot",
        ".NET Core",
        "Django",
        "FastAPI",
        "Flask",
        "GraphQL",
        "REST API Design",
        "Microservices",
        "Android Development",
        "iOS Development",
        "Flutter",
        "React Native",
        "HTML & CSS",
    ),
    C.ARCHITECTURE: (
        "Solution Architecture",
        "System Design",
        "Domain-Driven Design",
        "Event-Driven Architecture",
        "Integration Architecture",
        "API Management",
        "Enterprise Architecture",
    ),
    C.DEVOPS: (
        "Docker",
        "Kubernetes",
        "Terraform",
        "CI/CD",
        "Git",
        "Linux Administration",
        "Ansible",
        "Jenkins",
        "GitHub Actions",
        "Observability",
        "Prometheus",
        "Helm",
        "Site Reliability Engineering",
    ),
    C.DESIGN: (
        "UX Research",
        "Figma",
        "UI Design",
        "Interaction Design",
        "Design Systems",
        "Prototyping",
        "Usability Testing",
        "Information Architecture",
        "Visual Design",
        "Service Design",
    ),
    C.DATA_ANALYTICS: (
        "SQL",
        "Data Modeling",
        "Apache Spark",
        "Apache Kafka",
        "Apache Airflow",
        "dbt",
        "Pandas",
        "Power BI",
        "Tableau",
        "Machine Learning",
        "Deep Learning",
        "Natural Language Processing",
        "Statistics",
        "Data Warehousing",
        "ETL Design",
        "Snowflake",
        "Databricks",
        "PostgreSQL",
        "MongoDB",
        "Oracle Database",
        "Data Governance",
        "Looker",
        "MLOps",
        "Computer Vision",
    ),
    C.CLOUD: (
        "AWS",
        "Azure",
        "Google Cloud",
        "Cloud Architecture",
        "AWS Lambda",
        "Azure Functions",
        "Cloud Networking",
        "Cloud Cost Management",
    ),
    C.TESTING: (
        "Test Automation",
        "Selenium",
        "API Testing",
        "Cypress",
        "Performance Testing",
        "Test Strategy",
        "Manual Testing",
        "Playwright",
        "Mobile Testing",
        "Accessibility Testing",
    ),
    C.MANAGEMENT: (
        "Agile Delivery",
        "Stakeholder Management",
        "Scrum",
        "Project Planning",
        "Risk Management",
        "Requirements Analysis",
        "Product Roadmapping",
        "Kanban",
        "Budget Management",
        "Backlog Management",
        "Change Management",
        "SAFe",
    ),
    C.DOMAIN: (
        "Banking",
        "Insurance",
        "Retail",
        "Healthcare",
        "Telecommunications",
        "Energy & Utilities",
        "Public Sector",
        "Manufacturing",
        "Logistics",
        "Payments",
    ),
    C.SECURITY: (
        "Application Security",
        "Identity & Access Management",
        "Cloud Security",
        "Penetration Testing",
        "Security Operations",
        "Threat Modeling",
        "ISO 27001",
        "Vulnerability Management",
        "Cryptography",
        "Incident Response",
    ),
}


def _extended_skills() -> list[tuple[str, SkillCategory]]:
    out: list[tuple[str, SkillCategory]] = []
    services = (
        "Compute",
        "Storage",
        "Networking",
        "Databases",
        "Serverless",
        "Security",
        "Monitoring",
        "Data Engineering",
        "Machine Learning",
        "DevOps",
        "Containers",
        "Identity",
    )
    out += [(f"{c} {s}", C.CLOUD) for c in ("AWS", "Azure", "Google Cloud") for s in services]
    topics = ("Performance Tuning", "Testing", "Concurrency", "Security", "Packaging")
    langs = ("Python", "Java", "JavaScript", "TypeScript", "C#", "Go", "Kotlin")
    out += [(f"{lang} {t}", C.PROGRAMMING) for lang in langs for t in topics]
    capabilities = ("Regulation", "Data Standards", "Process Knowledge", "Customer Journeys")
    out += [(f"{d} {c}", C.DOMAIN) for d in _BASE_SKILLS[C.DOMAIN] for c in capabilities]
    data_tools = (
        "SQL",
        "Apache Spark",
        "Apache Kafka",
        "Power BI",
        "Tableau",
        "Snowflake",
        "Databricks",
    )
    out += [
        (f"{t} {s}", C.DATA_ANALYTICS)
        for t in data_tools
        for s in ("Optimization", "Administration", "Advanced Analytics")
    ]
    out += [
        (f"{a} Security {b}", C.SECURITY)
        for a in ("Application", "Network", "Data")
        for b in ("Assessment", "Engineering", "Compliance")
    ]
    out += [
        (f"{a} {b} Design", C.DESIGN) for a in ("Mobile", "Web", "Enterprise") for b in ("UX", "UI")
    ]
    out += [
        (f"{t} {s}", C.DEVOPS)
        for t in ("Kubernetes", "Docker", "Terraform", "Ansible")
        for s in ("Administration", "Security", "Automation")
    ]
    out += [
        (f"{t} {s}", C.TESTING)
        for t in ("Selenium", "Cypress", "Playwright")
        for s in ("Framework Design", "Scaling")
    ]
    out += [
        (f"{a} Management", C.MANAGEMENT)
        for a in ("Portfolio", "Vendor", "Release", "Program", "Capacity")
    ]
    out += [(f"{a} Architecture", C.ARCHITECTURE) for a in ("Data", "Security", "Application")]
    return out


def skill_catalogue() -> list[tuple[str, SkillCategory]]:
    """Ordered so that any prefix covers all categories (round-robin over base lists)."""
    ordered: list[tuple[str, SkillCategory]] = []
    pools = {cat: list(names) for cat, names in _BASE_SKILLS.items()}
    while any(pools.values()):
        for cat, names in pools.items():
            if names:
                ordered.append((names.pop(0), cat))
    seen: set[str] = set()
    result = []
    for name, cat in [*ordered, *_extended_skills()]:
        if name not in seen:
            seen.add(name)
            result.append((name, cat))
    return result


def skill_code(name: str) -> str:
    text = name.replace("C#", "CSHARP").replace("C++", "CPP").replace(".NET", "DOTNET")
    text = text.replace("&", "AND").replace(".js", "JS")
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


BUSINESS_UNITS = ("Digital", "Data & AI", "Cloud", "Enterprise Apps", "Security", "Consulting")
PROJECT_THEMES = (
    "Data Platform",
    "Mobile App",
    "Cloud Migration",
    "CRM Upgrade",
    "Analytics Portal",
    "Payments Modernisation",
    "Security Hardening",
    "ERP Integration",
    "Customer Portal",
    "AI Assistant",
    "API Gateway",
    "Core Banking Upgrade",
    "Claims Automation",
    "Supply Chain Visibility",
    "Observability Rollout",
)
