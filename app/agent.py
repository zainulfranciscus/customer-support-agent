# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import google.auth
from pydantic import BaseModel, Field

from google.adk.agents import Agent, Context
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import Workflow, FunctionNode, START
from google.genai import types

# Initialize credentials
_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


# State schemas
class WorkflowState(BaseModel):
    user_query: str = ""


class Classification(BaseModel):
    category: str = Field(
        description="The category of the user query. Must be 'shipping' if it is about shipping rates, tracking, delivery, or returns, and 'unrelated' otherwise."
    )


# Nodes implementation
def preprocess_query(ctx: Context, node_input: str) -> str:
    """Saves the user query to the workflow state so it can be passed to subsequent nodes."""
    ctx.state["user_query"] = node_input
    return node_input


preprocess_node = FunctionNode(func=preprocess_query, name="preprocess_node")

classifier_agent = Agent(
    name="classifier_agent",
    model=Gemini(
        model="gemini-3.1-flash-lite",
        retry_options=types.HttpRetryOptions(attempts=6),
    ),
    instruction=(
        "Analyze the user's input. Classify if the user query is related to shipping "
        "(shipping rates, package tracking, delivery status, returns process) or unrelated. "
        "Select either 'shipping' or 'unrelated' and output it as category in the required schema."
    ),
    output_schema=Classification,
)


def route_query(ctx: Context, node_input: Classification) -> str:
    """Inspects the classification category, sets the context routing, and returns the original query."""
    category = node_input.category.strip().lower()
    if "shipping" in category:
        ctx.route = "shipping"
    else:
        ctx.route = "unrelated"
    return ctx.state["user_query"]


router_node = FunctionNode(func=route_query, name="router_node")

shipping_faq_agent = Agent(
    name="shipping_faq_agent",
    model=Gemini(
        model="gemini-3.1-flash-lite",
        retry_options=types.HttpRetryOptions(attempts=6),
    ),
    instruction=(
        "You are a helpful customer support representative for a shipping company. "
        "Answer the customer's shipping-related query (regarding shipping rates, "
        "tracking, delivery, or returns) professionally, accurately, and politely."
    ),
)

decline_agent = Agent(
    name="decline_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=6),
    ),
    instruction=(
        "You are a polite customer support representative for a shipping company. "
        "The customer has asked an unrelated question. Politely decline to answer the question, "
        "explaining that you can only assist with shipping-related inquiries (rates, tracking, delivery, returns)."
    ),
)

# Workflow graph compilation
root_agent = Workflow(
    name="root_agent",
    state_schema=WorkflowState,
    edges=[
        (START, preprocess_node),
        (preprocess_node, classifier_agent),
        (classifier_agent, router_node),
        (router_node, {
            "shipping": shipping_faq_agent,
            "unrelated": decline_agent,
        }),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
