"""Requirement Checker Service for PaperFlow AI Stage 17.

Flow:
query → identify requirements → search user documents → search connected sources → match documents → Present/Missing

Handles:
- all present
- some missing
- none found
- duplicate documents
- ambiguous requirements
- clarification prompts for destination country and purpose
- authoritative source preservation
- non-official guidance disclaimer
"""

from __future__ import annotations

import logging
import re
from typing import Any

from models.requirement import (
    MatchedDocumentInfo,
    RequirementChecklistResponse,
    RequirementItem,
)
from services import retrieval_service
from storage import document_repository

logger = logging.getLogger("paperflow.requirement_service")

# Standard non-official disclaimer
VISA_DISCLAIMER = (
    "Note: These requirements are compiled for guidance based on standard checklists and do not "
    "constitute an official government determination. Please consult the official embassy or "
    "consulate website for definitive requirements."
)

# Common destination countries/regions
DESTINATION_PATTERNS: dict[str, list[str]] = {
    "United States": [r"\b(us|usa|u\.s\.|united\s+states|america)\b"],
    "United Kingdom": [r"\b(uk|u\.k\.|united\s+kingdom|britain|england)\b"],
    "Schengen Area": [r"\b(schengen|europe|eu)\b"],
    "Canada": [r"\b(canada)\b"],
    "Australia": [r"\b(australia|aus)\b"],
    "Germany": [r"\b(germany|deutschland)\b"],
    "France": [r"\b(france)\b"],
    "Japan": [r"\b(japan)\b"],
    "United Arab Emirates": [r"\b(dubai|uae|u\.a\.e\.|emirates)\b"],
    "Singapore": [r"\b(singapore)\b"],
    "Italy": [r"\b(italy)\b"],
    "Spain": [r"\b(spain)\b"],
}

PURPOSE_PATTERNS: dict[str, list[str]] = {
    "tourist": [r"\b(tourist|tourism|holiday|visit|visitor|travel|vacation)\b"],
    "student": [r"\b(student|study|university|college|education|academic)\b"],
    "work": [r"\b(work|employment|job|business|h1b|skilled)\b"],
    "transit": [r"\b(transit|layover)\b"],
}

# Requirement definitions with keywords and alternative names
VISA_REQUIREMENT_DEFINITIONS = [
    {
        "name": "Passport",
        "description": "Original valid passport with at least 6 months validity.",
        "keywords": ["passport", "pass_port"],
        "is_mandatory": True,
    },
    {
        "name": "Photo",
        "description": "Recent passport-size color photographs conforming to visa photo standards.",
        "keywords": ["photo", "photograph", "picture", "headshot", "portrait", "passport_photo"],
        "is_mandatory": True,
    },
    {
        "name": "Address Proof",
        "description": "Proof of residential address (e.g., utility bill, lease agreement, national ID/Aadhaar, or driver's license).",
        "keywords": ["address", "residence", "utility_bill", "electricity_bill", "lease", "rent_agreement", "aadhaar", "driving_license"],
        "is_mandatory": True,
    },
    {
        "name": "Proof of Funds",
        "description": "Recent bank statements or salary slips demonstrating sufficient financial means.",
        "keywords": ["bank_statement", "statement", "salary_slip", "pay_slip", "itr", "tax_return", "funds", "financial"],
        "is_mandatory": False,
    },
]


def is_requirement_query(query: str) -> bool:
    """Determine whether a user query asks for document requirements or checklist."""
    clean = query.lower().strip()
    if not clean:
        return False

    patterns = [
        r"\b(what\s+(documents?|docs?|papers?|things?)\s*(do\s+i|are)?\s*need(ed)?)\b",
        r"\b(what\s+do\s+i\s+need\s+(for|to))\b",
        r"\b(check\s+my\s+documents?|do\s+i\s+have\s+(everything|all))\b",
        r"\b(requirements?|checklist|documents?\s+needed)\b",
        r"\b(visa\s+documents?|documents?\s+for\s+a?\s*visa)\b",
    ]
    return any(re.search(p, clean) for p in patterns)


def extract_destination_and_purpose(query: str) -> tuple[str | None, str | None]:
    """Extract destination country and purpose of travel from user query."""
    clean = query.lower()
    detected_destination = None
    detected_purpose = None

    for country, patterns in DESTINATION_PATTERNS.items():
        if any(re.search(p, clean) for p in patterns):
            detected_destination = country
            break

    for purpose, patterns in PURPOSE_PATTERNS.items():
        if any(re.search(p, clean) for p in patterns):
            detected_purpose = purpose
            break

    return detected_destination, detected_purpose


async def check_requirements(
    query: str,
    user_id: str,
    destination: str | None = None,
    purpose: str | None = None,
    token: str | None = None,
) -> RequirementChecklistResponse:
    """Evaluate document requirements against user documents and connected sources.

    Strictly scopes document search to authenticated user_id.
    """
    clean_query = query.strip()
    extracted_dest, extracted_purp = extract_destination_and_purpose(clean_query)
    effective_dest = destination or extracted_dest
    effective_purpose = purpose or extracted_purp

    # Check for completely ambiguous queries lacking topic
    lower_query = clean_query.lower()
    is_visa_query = "visa" in lower_query
    is_passport_query = "passport" in lower_query and not is_visa_query

    requires_clarification = False
    clarification_prompt = None

    if not is_visa_query and not is_passport_query:
        # Ambiguous requirements query (e.g. "What do I need?", "What documents are required?")
        requires_clarification = True
        clarification_prompt = (
            "Could you please specify which application or destination country you are preparing for "
            "(e.g., US Tourist Visa, Schengen Visa, Passport Renewal) so I can verify your requirements?"
        )
    elif is_visa_query and not effective_dest:
        # Visa query without destination country
        requires_clarification = True
        clarification_prompt = (
            "Visa requirements vary by destination country and visa type (e.g. US, UK, Schengen; tourist, student, work). "
            "Which country and visa category are you applying for? Here is the checklist against standard baseline visa requirements:"
        )

    # Search for authoritative requirement sources in user documents/connected sources
    authoritative_source = await retrieval_service.find_authoritative_requirement_source(
        category="visa",
        destination=effective_dest,
        user_id=user_id,
        token=token,
    )

    # 1. Fetch user documents (strictly isolated to user_id)
    user_docs = document_repository.list_user_documents(owner_id=user_id, token=token)

    # 2. Match each requirement item against user's documents
    evaluated_items: list[RequirementItem] = []
    used_doc_ids: set[str] = set()

    for defn in VISA_REQUIREMENT_DEFINITIONS:
        req_name = defn["name"]
        desc = defn["description"]
        keywords = defn["keywords"]
        mandatory = defn["is_mandatory"]

        matching_docs = []
        for doc in user_docs:
            fname = (doc.original_filename or "").lower()
            meta_str = str(doc.metadata or {}).lower()

            matched = False
            for kw in keywords:
                kw_clean = kw.lower().replace("_", "")
                fname_clean = fname.replace("_", "").replace("-", "")
                if kw in fname or kw_clean in fname_clean:
                    matched = True
                    break
                if kw in meta_str:
                    matched = True
                    break

            if matched:
                matching_docs.append(doc)

        if matching_docs:
            # Handle duplicates: pick top document, note alternatives
            primary_doc = matching_docs[0]
            used_doc_ids.add(primary_doc.id)

            primary_info = MatchedDocumentInfo(
                id=primary_doc.id,
                filename=primary_doc.original_filename,
                source=primary_doc.source or "Local Storage",
                file_type=primary_doc.file_type,
                view_url=f"/api/documents/{primary_doc.id}/view",
                download_url=f"/api/documents/{primary_doc.id}/download",
            )

            duplicates_info = [
                MatchedDocumentInfo(
                    id=dup.id,
                    filename=dup.original_filename,
                    source=dup.source or "Local Storage",
                    file_type=dup.file_type,
                    view_url=f"/api/documents/{dup.id}/view",
                    download_url=f"/api/documents/{dup.id}/download",
                )
                for dup in matching_docs[1:]
            ]

            evaluated_items.append(
                RequirementItem(
                    name=req_name,
                    status="present",
                    matched_document=primary_info,
                    duplicates=duplicates_info,
                    description=desc,
                    is_mandatory=mandatory,
                )
            )
        else:
            # Missing document — strictly NO View or Download links
            evaluated_items.append(
                RequirementItem(
                    name=req_name,
                    status="missing",
                    matched_document=None,
                    duplicates=[],
                    description=desc,
                    is_mandatory=mandatory,
                )
            )

    present_count = sum(1 for item in evaluated_items if item.status == "present")
    missing_count = sum(1 for item in evaluated_items if item.status == "missing")
    total_required = len(evaluated_items)
    all_present = missing_count == 0

    # Compose clean summary text
    if all_present:
        summary_text = f"All {total_required} required documents are present in your records."
    elif present_count == 0:
        summary_text = f"None of the {total_required} required documents were found in your records."
    else:
        summary_text = f"{present_count} of {total_required} documents present. {missing_count} missing."

    return RequirementChecklistResponse(
        query=clean_query,
        category="visa" if is_visa_query else "general",
        destination=effective_dest,
        purpose=effective_purpose,
        requires_clarification=requires_clarification,
        clarification_prompt=clarification_prompt,
        disclaimer=VISA_DISCLAIMER,
        authoritative_source=authoritative_source,
        all_present=all_present,
        total_required=total_required,
        present_count=present_count,
        missing_count=missing_count,
        items=evaluated_items,
        summary=summary_text,
    )
