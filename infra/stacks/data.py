"""BrokebergData: the raw S3 bucket and the app-config secret.

Aurora is NOT in this stack. Free-plan accounts can only create Aurora PostgreSQL with express
configuration (no VPC, internet access gateway, IAM-only auth), which CloudFormation can't
express; `infra/scripts/express_db.py` creates and deletes it. Lambdas connect with IAM tokens
(see `db_connect_policy` in stacks/pipeline.py), so there is no DB password or DB secret.
"""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

APP_SECRET_NAME = "brokeberg/prod/app"


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = s3.Bucket(
            self,
            "Raw",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # The REPLAY archive: survives `cdk destroy`. Delete it by hand if you mean to.
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )

        # Starts empty and is never templated again, so a redeploy can't wipe it.
        # Filled by infra/scripts/push_secrets.py (provider flip, model IDs, source API keys,
        # DATABASE_URL + DB_IAM_AUTH).
        self.app_secret = secretsmanager.Secret(
            self,
            "App",
            secret_name=APP_SECRET_NAME,
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template="{}", generate_string_key="_placeholder"
            ),
        )

        CfnOutput(self, "RawBucketName", value=self.bucket.bucket_name)
