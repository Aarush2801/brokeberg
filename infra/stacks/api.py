"""BrokebergApi: the read-only query API (FastAPI via Mangum) behind a Lambda Function URL.

A Function URL rather than API Gateway: /api/query synthesis can outlast API Gateway's 29s cap.
The URL is public. Everything is read-only except /api/query, which calls the LLM, so set
`-c apiConcurrency=N` to cap concurrent invocations if the account's Lambda limit allows it.
"""

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from stacks.data import DataStack
from stacks.image import image_code
from stacks.pipeline import bedrock_policy


class ApiStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, data: DataStack, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        concurrency = self.node.try_get_context("apiConcurrency")
        fn = lambda_.DockerImageFunction(
            self,
            "Api",
            code=image_code("brokeberg.aws.api.handler"),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=1024,
            timeout=Duration.minutes(2),
            reserved_concurrent_executions=int(concurrency) if concurrency else None,
            log_group=logs.LogGroup(
                self,
                "ApiLogs",
                retention=logs.RetentionDays.TWO_WEEKS,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        data.app_secret.grant_read(fn)
        data.db_secret.grant_read(fn)
        fn.add_to_role_policy(bedrock_policy(self))

        url = fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
        CfnOutput(self, "ApiUrl", value=url.url)
