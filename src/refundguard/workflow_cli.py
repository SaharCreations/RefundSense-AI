"""Local demo identity flags are not authentication or production authorization."""

import json
import os

from .rules import Ruleset
from .workflow import Actor, ApprovalWorkflow, workflow_connection


def run_workflow(args, write_json):
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL to your development PostgreSQL database")
    rules = Ruleset(args.rules_config, args.data_dir / "policies")
    with workflow_connection(url) as conn:
        service = ApprovalWorkflow(conn, rules)
        if args.command == "workflow-init":
            service.setup()
            result = {"status": "workflow_schema_initialized", "demo_only": True}
        else:
            actor = Actor(args.organization_id, args.user_id)
            if args.command == "workflow-propose":
                result = service.propose(actor, args.order_id, args.customer_id, args.reason)
            elif args.command == "workflow-view":
                result = service.view(actor, args.workflow_id)
            elif args.command == "workflow-decide":
                result = service.decide(
                    actor, args.workflow_id, args.decision == "approve", args.payload_sha256
                )
            else:
                result = service.recover(actor, args.workflow_id)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0
