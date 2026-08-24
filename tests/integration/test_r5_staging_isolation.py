from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
STAGING_COMPOSE = ROOT / "deploy/docker/docker-compose.staging.yml"
DEPLOY_SCRIPT = ROOT / "deploy/deploy.sh"
PROD_COMPOSE = ROOT / "deploy/docker/docker-compose.prod.yml"


def _staging_config():
    return yaml.safe_load(STAGING_COMPOSE.read_text(encoding="utf-8"))


def test_staging_uses_explicit_isolated_storage_and_no_legacy_shared_paths():
    text = STAGING_COMPOSE.read_text(encoding="utf-8")
    assert "../../data" not in text
    assert "../../output" not in text
    assert "MINDMARGIN_STAGING_ROOT" in text
    assert "mindmargin_staging_redis_data" in text
    assert "mindmargin_staging_ollama_data" in text


def test_staging_has_explicit_internal_network_and_no_host_ports():
    config = _staging_config()
    services = config["services"]
    assert config["networks"]["staging_internal"]["internal"] is True
    assert config["networks"]["staging_internal"]["name"] == "mindmargin_staging_internal"
    for service in services.values():
        assert "ports" not in service
        assert service["networks"] == ["staging_internal"]


def test_staging_services_use_staging_environment_and_isolated_volume_names():
    config = _staging_config()
    assert config["volumes"]["mindmargin_staging_redis_data"]["name"] == "mindmargin_staging_redis_data"
    assert config["volumes"]["mindmargin_staging_ollama_data"]["name"] == "mindmargin_staging_ollama_data"
    assert config["services"]["api"]["environment"]["ENVIRONMENT"] == "staging"
    assert config["services"]["worker"]["environment"]["ENVIRONMENT"] == "staging"


def test_staging_mounts_are_not_production_mounts():
    config = _staging_config()
    for name in ("api", "worker"):
        mounts = config["services"][name]["volumes"]
        assert all("../../data" not in mount and "../../output" not in mount for mount in mounts)
        assert all("MINDMARGIN_STAGING_ROOT" in mount for mount in mounts)


def test_deploy_script_is_fail_closed_and_uses_staging_project():
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "MINDMARGIN_STAGING_ROOT" in text
    assert "Unsafe staging root overlaps protected root" in text
    assert "docker compose -p mindmargin-staging -f docker-compose.staging.yml" in text
    assert "docker-compose.prod.yml" not in text[text.index("cmd_staging()"):text.index("cmd_prod()")] 


def test_production_compose_remains_outside_r5a_allowlist_and_unchanged_reference_exists():
    assert PROD_COMPOSE.exists()
    production_text = PROD_COMPOSE.read_text(encoding="utf-8")
    assert "ENVIRONMENT: production" in production_text
