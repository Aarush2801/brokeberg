"""Create / inspect / delete the prod Aurora cluster (express configuration).

    cd pipeline && uv run python ../infra/scripts/express_db.py status|create|delete [--no-snapshot]

Free-plan accounts can only create Aurora PostgreSQL with express configuration: no VPC, an
internet access gateway, IAM-only auth, at most 4 ACU and 1 GB storage. CloudFormation has no
property for it, so this script owns the cluster's lifecycle instead of the BrokebergData stack.
`create` then sets 0-2 ACU with a 10-minute auto-pause (express defaults are fixed at create).
"""

import argparse
import time
from datetime import UTC, datetime
from typing import Any

import boto3

REGION = "us-east-2"
CLUSTER_ID = "brokeberg"
DB_NAME = "brokeberg"
DB_USER = "postgres"  # express default master user; IAM auth (rds_iam) is set up for it
SCALING = {"MinCapacity": 0, "MaxCapacity": 2, "SecondsUntilAutoPause": 600}
POLL_S = 15


def rds() -> Any:
    return boto3.client("rds", region_name=REGION)


def describe() -> dict[str, Any] | None:
    try:
        return dict(rds().describe_db_clusters(DBClusterIdentifier=CLUSTER_ID)["DBClusters"][0])
    except rds().exceptions.DBClusterNotFoundFault:
        return None


def endpoint() -> str:
    cluster = describe()
    if cluster is None:
        raise SystemExit(f"cluster {CLUSTER_ID!r} not found; run `express_db.py create` first")
    return str(cluster["Endpoint"])


def _wait(predicate: Any, what: str) -> None:
    while not predicate():
        print(f"  waiting for {what} ...")
        time.sleep(POLL_S)


def _instances_status() -> list[str]:
    cluster = describe()
    if cluster is None:
        return []
    ids = [m["DBInstanceIdentifier"] for m in cluster["DBClusterMembers"]]
    return [
        rds().describe_db_instances(DBInstanceIdentifier=i)["DBInstances"][0]["DBInstanceStatus"]
        for i in ids
    ]


def _available() -> bool:
    cluster = describe()
    statuses = _instances_status()
    return bool(
        cluster
        and cluster["Status"] == "available"
        and statuses
        and all(s == "available" for s in statuses)
    )


def status() -> None:
    cluster = describe()
    if cluster is None:
        print(f"{CLUSTER_ID}: not found")
        return
    keys = (
        "Status",
        "Endpoint",
        "Port",
        "EngineVersion",
        "DatabaseName",
        "MasterUsername",
        "DbClusterResourceId",
        "ServerlessV2ScalingConfiguration",
        "IAMDatabaseAuthenticationEnabled",
        "AllocatedStorage",
    )
    for key in keys:
        print(f"{key:36} {cluster.get(key)}")
    print(f"{'instances':36} {_instances_status()}")
    extra = {k: v for k, v in cluster.items() if "nternet" in k or "xpress" in k or "VPC" in k}
    for key, value in extra.items():
        print(f"{key:36} {value}")


def create() -> None:
    if describe() is not None:
        raise SystemExit(f"cluster {CLUSTER_ID!r} already exists")
    rds().create_db_cluster(
        DBClusterIdentifier=CLUSTER_ID,
        Engine="aurora-postgresql",
        WithExpressConfiguration=True,
        DatabaseName=DB_NAME,
        Tags=[{"Key": "project", "Value": "brokeberg"}],
    )
    _wait(_available, "cluster + instance available")
    rds().modify_db_cluster(
        DBClusterIdentifier=CLUSTER_ID,
        ServerlessV2ScalingConfiguration=SCALING,
        ApplyImmediately=True,
    )
    _wait(_available, "scaling change to apply")
    status()


def delete(snapshot: bool) -> None:
    cluster = describe()
    if cluster is None:
        print(f"{CLUSTER_ID}: not found")
        return
    for member in cluster["DBClusterMembers"]:
        rds().delete_db_instance(DBInstanceIdentifier=member["DBInstanceIdentifier"])
    _wait(lambda: not _instances_status(), "instances deleted")
    if snapshot:
        name = f"{CLUSTER_ID}-final-{datetime.now(UTC):%Y%m%d%H%M}"
        rds().delete_db_cluster(DBClusterIdentifier=CLUSTER_ID, FinalDBSnapshotIdentifier=name)
        print(f"final snapshot: {name}")
    else:
        rds().delete_db_cluster(DBClusterIdentifier=CLUSTER_ID, SkipFinalSnapshot=True)
    _wait(lambda: describe() is None, "cluster deleted")
    print(f"{CLUSTER_ID}: deleted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "create", "delete"))
    parser.add_argument("--no-snapshot", action="store_true", help="delete without a snapshot")
    args = parser.parse_args()
    if args.action == "status":
        status()
    elif args.action == "create":
        create()
    else:
        delete(snapshot=not args.no_snapshot)


if __name__ == "__main__":
    main()
