"""Eight fixed, read-only-to-production demo selections; run in disposable test databases."""

DEMOS = [
    {
        "id": "discovery",
        "title": "企业发现",
        "scope": "engineering",
        "nodes": [
            "tests/integration/test_evaluation.py::test_ranked_search_and_retrieval_are_measured_on_real_data"
        ],
    },
    {
        "id": "profile",
        "title": "企业画像",
        "scope": "protocol_only",
        "nodes": [
            "tests/integration/test_agents.py::test_all_workflows_structured_draft_and_usage[company_profile]"
        ],
    },
    {
        "id": "knowledge",
        "title": "私有知识与定位",
        "scope": "engineering",
        "nodes": [
            "tests/integration/test_private_knowledge.py::test_full_pipeline_all_supported_formats[pdf]"
        ],
    },
    {
        "id": "matching",
        "title": "项目匹配",
        "scope": "protocol_only",
        "nodes": [
            "tests/integration/test_agents.py::test_all_workflows_structured_draft_and_usage[project_match]"
        ],
    },
    {
        "id": "bp",
        "title": "BP 初筛",
        "scope": "protocol_only",
        "nodes": [
            "tests/integration/test_agents.py::test_all_workflows_structured_draft_and_usage[bp_screening]",
            "tests/integration/test_reports.py::test_report_from_agent_draft_preserves_provenance_and_bp_template",
        ],
    },
    {
        "id": "quality",
        "title": "数字与正式导出质量闸",
        "scope": "engineering",
        "nodes": [
            "tests/integration/test_reports.py::test_unregistered_number_blocks_formal_even_without_metric_rows",
            "tests/integration/test_reports.py::test_metric_review_approval_export_and_edit_invalidates_approval",
        ],
    },
    {
        "id": "isolation",
        "title": "机构、文档与导出隔离",
        "scope": "engineering",
        "nodes": [
            "tests/integration/test_private_knowledge_security.py::test_multi_organization_user_search_never_mixes_organizations",
            "tests/integration/test_reports.py::test_cross_org_unassigned_viewer_and_curator_export_denied",
            "tests/integration/test_evaluation.py::test_other_member_and_tenant_cannot_read_evaluation",
            "tests/integration/test_evaluation.py::test_idempotency_and_dataset_versions_are_bound_to_request_scope[organization]",
        ],
    },
    {
        "id": "recovery",
        "title": "任务失败和恢复",
        "scope": "protocol_only",
        "nodes": [
            "tests/unit/test_agent_gateway.py::test_timeout_is_bounded_and_not_implicitly_retried",
            "tests/integration/test_agents.py::test_error_retry_cap_and_prompt_tracking",
            "tests/integration/test_private_knowledge.py::test_parser_failure_retry_limit_and_recovery",
        ],
    },
]
