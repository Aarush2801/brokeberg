"""Brokeberg on AWS. Deploy stack by stack, reviewing `cdk diff` first:

    npx aws-cdk@2 deploy BrokebergData
    npx aws-cdk@2 deploy BrokebergPipeline
    npx aws-cdk@2 deploy BrokebergApi
"""

import os

import aws_cdk as cdk

from stacks.api import ApiStack
from stacks.data import DataStack
from stacks.pipeline import PipelineStack

app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-east-2")

data = DataStack(app, "BrokebergData", env=env)
PipelineStack(app, "BrokebergPipeline", data=data, env=env)
ApiStack(app, "BrokebergApi", data=data, env=env)

cdk.Tags.of(app).add("project", "brokeberg")
app.synth()
