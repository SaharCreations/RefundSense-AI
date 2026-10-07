"""Offline structural checks, not proof of container execution or AWS deployment."""

import json
from pathlib import Path

import jsonschema
import yaml
from dockerfile_parse import DockerfileParser

ROOT = Path(__file__).resolve().parents[1]


def main():
    schema = json.loads((ROOT / "infra/docker/compose.schema.json").read_text())
    for name in ["compose.yaml", "compose.llm.yaml"]:
        data = yaml.safe_load((ROOT / name).read_text())
        jsonschema.validate(data, schema)
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert set(compose["services"]) == {"db", "api", "web"}
    assert all(
        port.startswith("127.0.0.1:")
        for service in compose["services"].values()
        for port in service.get("ports", [])
    )
    assert "ports" not in compose["services"]["db"]
    assert compose["secrets"]["database_password"]["file"] == "./.local/database_password"
    for name in ["infra/docker/api.Dockerfile", "frontend/Dockerfile"]:
        with (ROOT / name).open() as handle:
            parser = DockerfileParser(fileobj=handle)
            assert parser.structure and parser.baseimage
            assert any(s["instruction"] == "USER" for s in parser.structure)
    # cfn-lint separately validates AWS resource types/properties/intrinsics.
    workflow = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    assert "--no-skips" in (ROOT / ".github/workflows/verify.yml").read_text()
    print(
        "Compose schema, loopback bindings, secret file, "
        "Dockerfile structure and CI gate checks passed."
    )


if __name__ == "__main__":
    main()
