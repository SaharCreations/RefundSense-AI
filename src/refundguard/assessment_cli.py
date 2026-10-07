import json
import os

from .orders import order_connection, read_order_customer, seed_demo
from .rules import Customer, Principal, RefundRequest, Ruleset, assess_refund
from .rules_evaluation import order_from_dict, score_cases


def run_assessment(args, write_json):
    ruleset = Ruleset(args.rules_config, args.data_dir / "policies")
    if args.command == "evaluate-rules":
        report = score_cases(args.data_dir / "rules_eval_cases.json", ruleset, args.split)
        output = args.output or args.report_directory / f"rules_{args.split}.json"
        write_json(output, report)
        print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
        return 0 if report["passed"] == report["count"] else 1
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL to your development PostgreSQL database")
    if args.command == "seed-demo":
        records = json.loads((args.data_dir / "demo_records.json").read_text())
        orders = [order_from_dict(facts) for facts in records["orders"]]
        customers = [Customer(**facts) for facts in records["customers"]]
        with order_connection(url, read_only=False) as conn:
            seed_demo(conn, orders, customers)
        print(
            json.dumps(
                {
                    "status": "demo_records_seeded",
                    "organization_id": "ORG-DEMO",
                    "orders": len(orders),
                    "customers": len(customers),
                    "existing_records_overwritten": False,
                },
                indent=2,
            )
        )
        return 0
    principal = Principal(args.organization_id)
    request = RefundRequest(
        args.order_id,
        args.customer_id,
        args.requested_on,
        args.reason,
        args.refund_method,
        args.include_shipping,
        args.include_tax,
    )
    with order_connection(url) as conn:
        order, customer = read_order_customer(conn, principal, request)
        result = assess_refund(principal, customer, order, request, ruleset)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0
