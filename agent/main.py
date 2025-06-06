import argparse
import asyncio
from collections.abc import Mapping
import contextlib
import itertools as it
import json
import logging
import os
from typing import Dict

from agents import Agent, OpenAIChatCompletionsModel, Runner
from agents.mcp import MCPServer, MCPServerSse
from agents.model_settings import ModelSettings
from agents import tracing
from openai import AsyncOpenAI, BadRequestError
import openstack
from rich.columns import Columns
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown
from rich.panel import Panel
from rich.pretty import Pretty


INSTRUCTIONS = '''
You are an OpenStack administrator and will answer questions about a specific deployment for which you have access via tools without needing to provide credentials (your username is {username} project name is {project_name} and project id is {project_id}).
Resources (VMs, flavors, images, volumes, etc) in OpenStack always have an ID (in UUID-4 form) and sometimes a name, but many tools only accept an ID to identify the resource.
Many of the resources have a tool ending in `_get` that can be used to list resources with few details with optional filtering, and another tool ending in `id_get` which for a given ID can return all the details.
Think carefully before answering as it may require calling multiple times one after the other.
For example to get details of a flavor by name you first need to get the ID using `flavors_get` and then use the ID to call `flavors_id_get` to get the details.
'''

MODEL_SETTINGS = dict(
    tool_choice='auto',  # auto, required, None
    temperature=0.0,
    parallel_tool_calls=True,  # defaults to False
    extra_body={"options": { "num_ctx": 40960 } }
    # top_p
    # frequency_penalty
    # frequency_penalty
    # truncation
    # max_tokens
    # reasoning
    # metadata
    # store
    # include_usage
    # extra_query
    # extra_headers
)


def parse_args():
    parser = argparse.ArgumentParser(description="Basic MCP agent")
    parser.add_argument('--verbose', '-v',
                        action='count', default=0,
                        help="Verbose run")
    parser.add_argument('--config', '-c',
                        type=str, default='./agent.json',
                        help="JSON file with configuration")
    parser.add_argument('--model', '-m',
                        type=str, default='',
                        help="Override model to use")
    args = parser.parse_args()
    return args


class DynamicDict(Mapping):
    def __init__(self, generators):
        self._generators = generators

    def __getitem__(self, key):
        if key in self._generators:
            return self._generators[key]()
        raise KeyError(key)

    def __contains__(self, key):
        return key in self._generators

    def __repr__(self):
        return f"DynamicDict(generators={repr(self._generators)})"

    def keys(self):
        return self._generators.keys()

    def __iter__(self):
        return self._generators.__iter__()

    def items(self):
        return [(key, self[key]) for key in self._generators]

    def __len__(self):
        return len(self._generators)


async def get_tools(mcp_servers):
    tools = []
    for server in mcp_servers:
        server_tools = await server.list_tools()
        tools.extend(server_tools)
    return tools


def show_tools(console, tools):
    tools_renderable = [Panel(f'[yellow]{t.name}[/yellow]\n[b]{t.annotations.title}[/b]',
                              expand=True)
                        for t in tools]
    console.print(f'[b]Available tools {len(tools)}:[/b]',
                  Columns(tools_renderable))


def print_usage(console, usage):
    usage = vars(usage)
    pretty_usage = Pretty(usage, indent_guides=True)
    panel = Panel(pretty_usage, title="Usage", style="blue")
    console.print(panel)


async def create_mcp_servers(stack, servers, headers):
    result = []
    for i, server_cfg in enumerate(servers):
        config = server_cfg['config']
        server = MCPServerSse(name=f'SSE Python Server {i}',
                              cache_tools_list=True,
                              params={'url': config['url'],
                                      'headers': headers},
                              client_session_timeout_seconds=config.get('timeout'))
        result.append(await stack.enter_async_context(server))
    return result


async def main(config: Dict, osp, args):
    console = Console()

    if config['api_key'].startswith('os.environ/'):
        config['api_key'] = os.environ(config['api_key'][11:])
    if config['api_key'].startswith('open/'):
        config['api_key'] = open(config['api_key'][5:], 'r').read().strip('\n')

    client = AsyncOpenAI(base_url=config['base_url'], api_key=config['api_key'])
    model = args.model or config['model']
    llm = OpenAIChatCompletionsModel(model=model, openai_client=client)

    osp_headers = DynamicDict({'X-Auth-Token': lambda: osp.auth_token})
    instructions = INSTRUCTIONS.format(username=osp.auth['username'],
                                       project_name=osp.auth['project_name'],
                                       project_id=osp.current_project_id)

    try:
        async with contextlib.AsyncExitStack() as stack:
            mcp_servers = await create_mcp_servers(stack, config['servers'], osp_headers)
            agent = Agent(name="Assistant",
                          instructions=instructions,
                          mcp_servers=mcp_servers,
                          model_settings=ModelSettings(**MODEL_SETTINGS),
                          model=llm)

            tools = await get_tools(mcp_servers)
            console.print(f"[b]LLM[/b]: [blue]{model} @ {config['base_url']}[/blue] Tools: {len(tools)}")
            if args.verbose:
                show_tools(console, tools)

            while True:
                message = console.input('[bold red]>>> [/bold red]')
                try:
                    with console.status('[bold green]Thinking...[/bold green]'):
                        result = await Runner.run(starting_agent=agent, input=message)
                    res = Markdown(result.final_output)
                    console.print(Panel(res, title='Agent response', style='green'))
                    if args.verbose:
                        print_usage(console, result.context_wrapper.usage)
                except BadRequestError as exc:
                    console.print(f'[bold red]Error: {exc.body}[/bold red]')
    # Handle Ctrl+D and Ctrl+C
    except (EOFError, KeyboardInterrupt, asyncio.exceptions.CancelledError) as exc:
        pass

    console.print()


def set_logging(verbose):
    handler = RichHandler()
    level = 'DEBUG' if verbose >= 4 else 'ERROR'
    logging.basicConfig(level=level, handlers=[handler])
    # logging.basicConfig(level=logging.ERROR)
    if verbose >= 2:
        logger = logging.getLogger("openai.agents")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        os.putenv('OPENAI_AGENTS_DONT_LOG_TOOL_DATA', '0')
        os.putenv('OPENAI_AGENTS_DONT_LOG_MODEL_DATA', '1')

    if verbose >= 3:
        os.putenv('OPENAI_AGENTS_DONT_LOG_MODEL_DATA', '0')


def set_tracing():
    tracing.set_tracing_disabled(True)


if __name__ == "__main__":
    args = parse_args()
    set_logging(args.verbose)
    set_tracing()
    config = json.loads(open(args.config, 'r').read())
    osp = openstack.connect(verify=False)
    asyncio.run(main(config, osp, args))
