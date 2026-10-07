# Optional AWS deployment preparation

The demo runs locally without AWS. The files here are prepared and offline-validated, not deployed. No AWS account was accessed and no resource was created.

`infra/aws/stack.yaml` prepares one ECS Fargate task containing the existing Next.js and FastAPI processes, RDS PostgreSQL 17.11, an HTTPS Application Load Balancer and a private versioned S3 artifact bucket. It preserves the original two-application architecture; SQL and LangGraph state persist in RDS. S3 is for explicitly uploaded policy/evaluation artifacts, not order retrieval. No queue, Redis, Kubernetes or Lambda layer is added.

Required operator inputs are digest-pinned API/web image URIs, an existing regional ACM certificate and the exact HTTPS origin. Build the API image with the dense model baked in and the frontend production target. There is no automatic LLM model deployment; its experimental output is not required for the workflow.

The task defaults to desired count zero. **Creating the stack still creates paid infrastructure**, even with zero running tasks. Do not create it merely to preview the template. Local demo use remains free of paid services.

## Prepared deployment sequence (not executed)

1. Complete the native PostgreSQL and Docker CI gates.
2. Review region, images, domain/certificate and desired resources. Obtain approval for actual hosting.
3. Build and push the two images to an operator-owned ECR repository; resolve their immutable sha256 digests.
4. Validate and review a CloudFormation change set using `infra/aws/parameters.example.json`. Supply actual values in a private copy under `.local/`.
5. Deploy only the approved change set. Review default snapshots/retention and deletion protection before creation.
6. Start the single ECS service, configure DNS to the ALB and use authenticated ECS Exec for trusted setup. Inside the API container run, through `python scripts/container_entrypoint.py`, the existing `refundguard seed-demo`, `workflow-init`, `auth-init`, and `--model-dir .cache/model ingest --output /tmp/ingestion.json` commands. Ingestion initializes the `vector` extension using the database owner.
7. Provision support/reviewer SQL accounts interactively through the trusted CLI. Do not put their passwords in task definitions, CLI arguments, GitHub secrets or deployment outputs.
8. Run the same approval/revalidation/idempotency checks against the deployed synthetic demo. Archive measured reports to the private S3 bucket explicitly. The application does not upload automatically.

## Boundaries

Only port 443 reaches the ALB; only the ALB can reach the web container. FastAPI is accessed over task loopback. Tasks have public egress addresses for ECR/CloudWatch/Secrets Manager access but no public ingress rule; RDS is in private subnets with access only from the app security group. There is no NAT gateway. Single-AZ RDS and one app task are deliberate demo settings, not an availability claim.

Database credentials are generated in Secrets Manager, delivered through ECS secret references, and URL-encoded by the container entrypoint. RDS connections use `verify-full` with the bundled official Amazon RDS CA certificates. `infra/aws/rds-ca.pem` came from https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem; review/refresh the trust bundle before deployment. Credential rotation is not automated by this template.

HTTPS origin validation and Secure cookies stay enabled in the production frontend. No account/password is seeded publicly. The template's schema/semantics were checked with cfn-lint; this is not proof of region capacity, certificate ownership, IAM permission, connectivity or successful deployment. The database owner is used for this synthetic demo's schema setup; real production use needs separately reviewed database roles and operations.

Official references:
- https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ecs-taskdefinition.html
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html
- https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-versions.html
