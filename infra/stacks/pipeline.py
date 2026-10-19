"""BrokebergPipeline: one scheduled ingest Lambda per connector -> FIFO queue -> process Lambda
(extract -> cluster -> graph). Destroying this stack stops every schedule and all Bedrock spend.
"""

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_scheduler_targets as targets
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from stacks.data import DataStack
from stacks.image import image_code

# UTC. Congress every 6h rather than hourly so Aurora gets idle windows to pause in.
SCHEDULES: dict[str, str] = {
    "fred": "cron(0 14 * * ? *)",
    "bls": "cron(30 13 * * ? *)",
    "congress": "cron(0 */6 * * ? *)",
    "senate_votes": "cron(15 */6 * * ? *)",
    "fec": "cron(0 15 * * ? *)",
    "ratings": "cron(0 16 ? * MON *)",
    # ~75 posts/day: live accounts x X_MAX_RESULTS=5 over a 1-day window (ceiling 100).
    "x": "cron(0 13 * * ? *)",
}
EXTRACT_DAILY_CAP = "30"


def bedrock_policy(stack: Stack) -> iam.PolicyStatement:
    return iam.PolicyStatement(
        actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources=[
            # Cross-region (us.) profiles route to foundation models in other US regions.
            "arn:aws:bedrock:*::foundation-model/anthropic.*",
            "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
            f"arn:aws:bedrock:{stack.region}:{stack.account}:inference-profile/us.anthropic.*",
        ],
    )


# Aurora's master user (infra/scripts/express_db.py); express clusters accept only IAM auth.
DB_USER = "postgres"


def db_connect_policy(stack: Stack) -> iam.PolicyStatement:
    """IAM DB auth for the express cluster. Its resource ID only exists after express_db.py
    creates it outside CloudFormation, hence the `cluster-*` wildcard (one cluster per account
    here; the free plan allows two)."""
    return iam.PolicyStatement(
        actions=["rds-db:connect"],
        resources=[f"arn:aws:rds-db:{stack.region}:{stack.account}:dbuser:cluster-*/{DB_USER}"],
    )


class PipelineStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, data: DataStack, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dlq = sqs.Queue(self, "ProcessDlq", fifo=True, retention_period=Duration.days(14))
        queue = sqs.Queue(
            self,
            "ProcessQueue",
            fifo=True,
            visibility_timeout=Duration.minutes(90),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=2),
        )

        def function(
            name: str, handler: str, timeout: Duration, env: dict[str, str]
        ) -> lambda_.DockerImageFunction:
            fn = lambda_.DockerImageFunction(
                self,
                name,
                code=image_code(handler),
                architecture=lambda_.Architecture.ARM_64,
                memory_size=1024,
                timeout=timeout,
                environment=env,
                log_group=logs.LogGroup(
                    self,
                    f"{name}Logs",
                    retention=logs.RetentionDays.TWO_WEEKS,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            )
            data.app_secret.grant_read(fn)
            fn.add_to_role_policy(db_connect_policy(self))
            fn.add_to_role_policy(bedrock_policy(self))
            return fn

        for source, cron in SCHEDULES.items():
            name = "Ingest" + "".join(p.title() for p in source.split("_"))
            fn = function(
                name,
                "brokeberg.aws.handlers.ingest",
                Duration.minutes(10),
                {"SOURCE": source, "PROCESS_QUEUE_URL": queue.queue_url},
            )
            data.bucket.grant_put(fn)
            queue.grant_send_messages(fn)
            scheduler.Schedule(
                self,
                f"{name}Schedule",
                schedule=scheduler.ScheduleExpression.expression(cron),
                # No retries: X bills per read; the next scheduled pull catches up (dedup by hash).
                target=targets.LambdaInvoke(fn, retry_attempts=0),
            )

        process = function(
            "Process",
            "brokeberg.aws.handlers.process",
            Duration.minutes(15),
            {"EXTRACT_DAILY_CAP": EXTRACT_DAILY_CAP},
        )
        process.add_event_source(event_sources.SqsEventSource(queue, batch_size=1))
