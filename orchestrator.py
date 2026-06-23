import asyncio
import os
import sys
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run_orchestrator(prompt: str, mock_token: str):
    """
    Orchestrates the interaction between a local LLM (via Ollama) and the MCP server.
    """
    # 1. Define the parameters to start the local MCP server
    # We run the server as a module (-m) so that absolute imports like 'src.auth' work correctly.
    # We also ensure the current environment variables are passed down.
    env = os.environ.copy()
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tools.mcp_server"],
        env=env,
        stderr=sys.stderr  # Pulls the background crash into view
    )

    # 2. Establish a connection to the MCP server via stdio
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 3. Create a LangChain tool wrapper for the MCP 'secure_data_lookup' tool
            @tool
            async def secure_data_lookup(obo_token: str) -> str:
                """
                Retrieves internal account status or secure data. Requires a valid auth_token.
                """
                result = await session.call_tool("secure_data_lookup", arguments={"obo_token": obo_token})
                return result.content[0].text

            # 4. Initialize the Local LLM client (using Ollama)
            # Requires: pip install langchain-ollama
            llm = ChatOllama(model="llama3.1", temperature=0).bind_tools([secure_data_lookup])

            # 5. Build the prompt context
            # We pass the user token to the LLM context so it can fulfill tool requirements
            messages = [
                SystemMessage(content=f"You are a secure agent. Use the tools provided. User Session Token: {mock_token}"),
                HumanMessage(content=prompt)
            ]

            # 6. Run the LLM and handle tool execution logic
            print(f"--- Sending prompt to LLM: '{prompt}' ---")
            try:
                response = await llm.ainvoke(messages)
                
                if response.tool_calls:
                    # Add the initial AI message with tool calls to the history context
                    messages.append(response)
                    
                    for tool_call in response.tool_calls:
                        print(f"--- LLM is executing tool: {tool_call['name']} ---")
                        output = await secure_data_lookup.ainvoke(tool_call["args"])
                        # Add the specific tool output to the history
                        messages.append(ToolMessage(content=output, tool_call_id=tool_call["id"]))
                    
                    # Get the final answer from the LLM now that it has the tool results
                    final_response = await llm.ainvoke(messages)
                    print(f"\nFinal Result:\n{final_response.content}")
                else:
                    print(f"\nFinal Result:\n{response.content}")
            except httpx.ConnectError:
                print("\n❌ Error: Connection to Ollama failed.")
                print("Check that 'ollama serve' is running and accessible at http://localhost:11434")

if __name__ == "__main__":
    # Mock data for demonstration
    MOCK_TOKEN = "MOCK_AZURE_AD_TOKEN_FOR_TESTING_PURPOSES_12345"
    USER_PROMPT = "What is my account status?"
    
    asyncio.run(run_orchestrator(USER_PROMPT, MOCK_TOKEN))