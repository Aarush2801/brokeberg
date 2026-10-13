"""The one Lambda image every function runs; each picks its handler via CMD."""

from pathlib import Path

from aws_cdk import IgnoreMode
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_lambda as lambda_

REPO_ROOT = Path(__file__).resolve().parents[2]


def image_code(handler: str) -> lambda_.DockerImageCode:
    return lambda_.DockerImageCode.from_image_asset(
        str(REPO_ROOT),
        file="infra/Dockerfile",
        cmd=[handler],
        platform=ecr_assets.Platform.LINUX_ARM64,
        ignore_mode=IgnoreMode.DOCKER,  # honour /.dockerignore (allowlist; keeps .env out)
    )
