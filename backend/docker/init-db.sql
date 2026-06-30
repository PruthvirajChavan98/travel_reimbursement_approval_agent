-- Create the two databases the stack needs: one for the LangGraph checkpointer,
-- one for Langfuse. Run automatically by the postgres entrypoint on first init.
CREATE DATABASE checkpointer;
CREATE DATABASE langfuse;
