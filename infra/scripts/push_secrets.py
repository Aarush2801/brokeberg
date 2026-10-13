"""Write the prod app config to Secrets Manager (`brokeberg/prod/app`).

    cd pipeline && uv run python ../infra/scripts/push_secrets.py --sonnet <Sonnet 5.5 profile ID>

Source API keys come from the repo-root .env (never committed); the provider flip and model IDs
are set here; S3_RAW_BUCKET comes from the BrokebergData stack output. Prints key names only.
Re-run after any change; it replaces the whole secret.
"""

import argparse
import json
from pathlib import Path

import boto3
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
REGION = "us-east-1"
SECRET_ID = "brokeberg/prod/app"
SOURCE_KEYS = (
    "CONGRESS_API_KEY",
    "FRED_API_KEY",
    "BLS_API_KEY",
    "DATA_GOV_API_KEY",
    "CENSUS_API_KEY",
    "X_BEARER_TOKEN",
)
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def stack_output(name: str) -> str:
    cfn = boto3.client("cloudformation", region_name=REGION)
    outputs = cfn.describe_stacks(StackName="BrokebergData")["Stacks"][0]["Outputs"]
    return next(o["OutputValue"] for o in outputs if o["OutputKey"] == name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sonnet", required=True, help="Sonnet 5.5 inference-profile ID")
    parser.add_argument("--haiku", default=HAIKU)
    args = parser.parse_args()

    env = dotenv_values(REPO_ROOT / ".env")
    missing = [k for k in SOURCE_KEYS if not env.get(k)]
    secret = {k: env[k] for k in SOURCE_KEYS if env.get(k)}
    secret |= {
        "LLM_PROVIDER": "bedrock",
        "LLM_MODEL": args.sonnet,
        "LLM_MODEL_CHEAP": args.haiku,
        "EMBED_PROVIDER": "bedrock",
        "EMBED_MODEL": "amazon.titan-embed-text-v2:0",
        "EMBED_DIM": "1024",
        "AWS_REGION": REGION,
        "S3_RAW_BUCKET": stack_output("RawBucketName"),
    }
    boto3.client("secretsmanager", region_name=REGION).put_secret_value(
        SecretId=SECRET_ID, SecretString=json.dumps(secret)
    )
    print(f"wrote {SECRET_ID}: {', '.join(sorted(secret))}")
    if missing:
        print(f"not in .env (connectors needing them will fail): {', '.join(missing)}")


if __name__ == "__main__":
    main()
