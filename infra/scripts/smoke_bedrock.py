"""Phase-0 Bedrock preflight: list the Anthropic inference profiles, then run one structured-output
call per model through the real `brokeberg.llm.complete` path, plus one Titan embedding.

    cd pipeline && uv run python ../infra/scripts/smoke_bedrock.py [--sonnet ID] [--haiku ID]

Costs well under $0.01. Prints the IDs to put in the app secret.
"""

import argparse
import os
import sys

import boto3
from pydantic import BaseModel

os.environ.update({"LLM_PROVIDER": "bedrock", "EMBED_PROVIDER": "bedrock"})
os.environ.setdefault("AWS_REGION", "us-east-2")
os.environ["EMBED_MODEL"] = "amazon.titan-embed-text-v2:0"

from brokeberg import llm  # noqa: E402
from brokeberg.embed import embed  # noqa: E402

SONNET = "us.anthropic.claude-sonnet-4-6"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


class Capital(BaseModel):
    country: str
    capital: str


def profiles() -> list[str]:
    client = boto3.client("bedrock", region_name=os.environ["AWS_REGION"])
    ids: list[str] = []
    for page in client.get_paginator("list_inference_profiles").paginate():
        ids += [p["inferenceProfileId"] for p in page["inferenceProfileSummaries"]]
    return sorted(i for i in ids if "anthropic" in i)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sonnet", default=SONNET)
    parser.add_argument("--haiku", default=HAIKU)
    args = parser.parse_args()

    found = profiles()
    print("Anthropic inference profiles:\n  " + "\n  ".join(found))
    sonnet = args.sonnet

    ok = True
    for label, model in (("sonnet", sonnet), ("haiku", args.haiku)):
        try:
            out = llm.complete("Capital of France?", schema=Capital, model=model, max_tokens=2000)
            print(f"OK   {label:<6} {model}: {out}")
        except Exception as e:  # noqa: BLE001 - report every model, then fail
            ok = False
            print(f"FAIL {label:<6} {model}: {type(e).__name__}: {e}")
    try:
        print(f"OK   titan  dim={len(embed(['hello'])[0])}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"FAIL titan: {type(e).__name__}: {e}")
    if ok:
        print(f"\nLLM_MODEL={sonnet}\nLLM_MODEL_CHEAP={args.haiku}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
