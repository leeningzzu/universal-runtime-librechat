from pathlib import Path


SOURCE = Path("src/universal_runtime/web_general_chat_formal_prepare.py")


def test_streaming_project_instructions_currentness_reads_nested_job_bundle_payload():
    project_instructions_sha256 = "a" * 64
    job_bundle_record = {
        "schema": "RUNTIME_IMMUTABLE_JOB_BUNDLE_BINDING_V1",
        "job_id": "JOB_TEST",
        "job_bundle": {
            "project_instructions_sha256": project_instructions_sha256,
        },
        "job_bundle_sha256": "b" * 64,
    }

    # The immutable JobBundle record is a wrapper. Project-instruction identity
    # is owned by the nested committed JobBundle payload, never the wrapper.
    assert job_bundle_record.get("project_instructions_sha256") is None
    assert job_bundle_record["job_bundle"]["project_instructions_sha256"] == project_instructions_sha256

    source = SOURCE.read_text(encoding="utf-8")
    assert 'job_bundle_record.get("project_instructions_sha256")' not in source
    assert 'job_bundle.get("project_instructions_sha256")' in source
