"""BrokebergData: Aurora PostgreSQL Serverless v2 (pgvector), the raw S3 bucket, and the secrets.

Stateful and cheap at rest: Aurora scales to 0 ACU and auto-pauses when idle. Destroying this
stack leaves a final Aurora snapshot (RemovalPolicy.SNAPSHOT).
"""

from aws_cdk import Annotations, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

APP_SECRET_NAME = "brokeberg/prod/app"
DB_SECRET_NAME = "brokeberg/prod/db"
DB_NAME = "brokeberg"


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Public subnets only, no NAT: Lambdas run outside the VPC and reach Aurora's public
        # endpoint over TLS (a NAT gateway would cost ~$33/mo).
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)
            ],
        )
        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, allow_all_outbound=False)
        db_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(5432),
            "Lambda has no fixed egress IPs; protected by forced TLS + generated password",
        )

        engine = rds.DatabaseClusterEngine.aurora_postgres(
            version=rds.AuroraPostgresEngineVersion.VER_16_9
        )
        self.cluster = rds.DatabaseCluster(
            self,
            "Db",
            engine=engine,
            credentials=rds.Credentials.from_generated_secret(
                "brokeberg",
                secret_name=DB_SECRET_NAME,
                exclude_characters=" %+~`#$&*()|[]{}:;<>?!'/@\"\\",
            ),
            default_database_name=DB_NAME,
            writer=rds.ClusterInstance.serverless_v2("writer", publicly_accessible=True),
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=2,
            serverless_v2_auto_pause_duration=Duration.minutes(10),
            parameter_group=rds.ParameterGroup(
                self, "Params", engine=engine, parameters={"rds.force_ssl": "1"}
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[db_sg],
            storage_encrypted=True,
            backup=rds.BackupProps(retention=Duration.days(1)),
            removal_policy=RemovalPolicy.SNAPSHOT,
        )
        # Public Aurora is the chosen trade-off (no NAT); synth still notes W9011.
        Annotations.of(db_sg).acknowledge_warning(
            "CloudFormation-Validate::W2508",
            "Public Aurora by design: Lambdas run outside the VPC; TLS forced, generated password",
        )
        assert self.cluster.secret is not None
        self.db_secret = self.cluster.secret

        self.bucket = s3.Bucket(
            self,
            "Raw",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Starts empty and is never templated again, so a redeploy can't wipe it.
        # Filled by infra/scripts/push_secrets.py (provider flip, model IDs, source API keys).
        self.app_secret = secretsmanager.Secret(
            self,
            "App",
            secret_name=APP_SECRET_NAME,
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template="{}", generate_string_key="_placeholder"
            ),
        )

        CfnOutput(self, "RawBucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "DbEndpoint", value=self.cluster.cluster_endpoint.hostname)
