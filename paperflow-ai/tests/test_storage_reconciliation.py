from __future__ import annotations

from storage.supabase_storage import get_storage_bucket_name, parse_storage_object_owner


def test_storage_bucket_name_matches_private_bucket_contract() -> None:
    assert get_storage_bucket_name() == "paperflow-documents"


def test_parse_storage_object_owner_extracts_user_namespace() -> None:
    owner = parse_storage_object_owner(
        "11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/report.pdf"
    )
    assert owner == "11111111-1111-4111-8111-111111111111"


def test_parse_storage_object_owner_rejects_non_user_scoped_paths() -> None:
    assert parse_storage_object_owner("report.pdf") is None
