# Repository preparation and publication

The supplied Git bundle contains a local `main` branch and the prepared commit history. No remote repository has been created and nothing has been pushed. Local author metadata uses `RefundGuard preparation <repo-preparation@example.invalid>`; it does not claim the owner's identity.

Restore the portable repository from the bundle placed alongside the project folder in the ZIP:

```bash
git clone --branch main RefundSense_AI.git.bundle refundsense-ai
cd refundsense-ai
git remote remove origin
```

Alternatively, use the extracted working tree and initialize Git yourself. The bundle is the copy with prepared history.

After choosing a GitHub repository owned by you, publication is a separate step:

```bash
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

Use a new empty remote to avoid overwriting existing work. Configure your own Git identity for future commits. No license has been selected; choose the owner's preferred license before representing this project as open source.

After the first push, inspect both GitHub Actions jobs. Do not mark Docker/native PostgreSQL gates passed until the workflow reports them. Set branch protection for `main` to require those checks after their first run. Optionally enable private vulnerability reporting. No deployment credentials or AWS account are needed for the existing verification workflow.

Generated environments, caches, credentials, latest-run reports and model weights are excluded. Frozen evaluation evidence and the recorded walkthrough are included. AWS deployment remains separate and can create paid resources; no deployment is performed by this repository workflow.
