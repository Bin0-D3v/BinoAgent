from __future__ import annotations

import random
import sys
import time
from datetime import datetime
from typing import Optional

import typer
from dotenv import load_dotenv

from . import db, memory
from .agent import TwitterAgent
from .poster import post_to_x

load_dotenv()

app = typer.Typer(help="Twitter agent powered by OpenAI with persistent memory.")
memory_app = typer.Typer(help="Manage the agent memory bank.")
app.add_typer(memory_app, name="memory")


@app.callback()
def bootstrap() -> None:
    """
    Ensure database tables exist before running any commands.
    """
    try:
        db.init_db()
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(f"Failed to initialize database: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@memory_app.command("add")
def memory_add(
    key: str = typer.Argument(..., help="Short label for the memory entry."),
    value: str = typer.Argument(..., help="Details to store."),
) -> None:
    entry = memory.remember(key=key, value=value)
    typer.echo(f"Stored memory #{entry.id} ({entry.key}).")


@memory_app.command("list")
def memory_list(
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum number of entries to show."),
) -> None:
    entries = memory.recall(limit=limit)
    if not entries:
        typer.echo("Memory is empty.")
        return
    for entry in entries:
        typer.echo(f"[{entry.created_at:%Y-%m-%d %H:%M}] {entry.key}: {entry.value}")


@app.command()
def suggest(
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic or theme for the tweet."),
    instructions: Optional[str] = typer.Option(
        None,
        "--instructions",
        "-i",
        help="Additional guidance (tone, call-to-action, etc.).",
    ),
) -> None:
    agent = TwitterAgent()
    tweet = agent.draft_tweet(topic=topic, instructions=instructions)
    typer.echo(tweet)


@app.command("prepare")
def prepare(
    text: Optional[str] = typer.Option(
        None,
        "--text",
        "-x",
        help="Tweet content. If omitted, a draft will be generated first.",
    ),
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic for draft generation."),
    instructions: Optional[str] = typer.Option(
        None, "--instructions", "-i", help="Extra guidance when generating a draft."
    ),
    copy_to_clipboard: bool = typer.Option(
        False,
        "--copy",
        help="Copy the final tweet to the clipboard for manual posting.",
    ),
) -> None:
    agent = TwitterAgent()
    final_text = text

    if not final_text:
        typer.echo("Generating draft tweet...")
        final_text = agent.draft_tweet(topic=topic, instructions=instructions)
        typer.echo("\nDraft:\n")
        typer.echo(final_text)
        typer.echo("")

    if copy_to_clipboard:
        try:
            import pyperclip
        except ImportError as exc:  # pragma: no cover - dependency issue
            typer.echo(f"Clipboard support unavailable: {exc}", err=True)
        else:
            pyperclip.copy(final_text)
            typer.echo("Tweet copied to clipboard.")

    typer.echo("Manual posting steps:")
    typer.echo("1. Open twitter.com/compose/tweet in your browser.")
    typer.echo("2. Paste the generated tweet.")
    typer.echo("3. Review and post.")


@app.command("autopost")
def autopost(
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic for generating the tweet."),
    instructions: Optional[str] = typer.Option(
        None, "--instructions", "-i", help="Additional hints to guide the tone or content."
    ),
    node_path: str = typer.Option("node", "--node-path", help="Custom path to Node.js binary if needed."),
) -> None:
    agent = TwitterAgent()
    typer.echo("Generating Bino's latest take...")
    tweet = agent.draft_tweet(topic=topic, instructions=instructions)
    typer.echo("Tweet generated:\n")
    typer.echo(tweet)
    typer.echo("")

    confirm = typer.confirm("Post this to X automatically? (requires cookies setup)", default=False)
    if not confirm:
        typer.echo("Aborted.")
        raise typer.Exit(code=0)

    try:
        post_to_x(tweet_text=tweet, node_bin=node_path)
    except Exception as exc:
        typer.echo(f"Auto-post failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Auto-post triggered successfully.")


@app.command("autoloop")
def autoloop(
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Topic for generating each tweet."),
    instructions: Optional[str] = typer.Option(
        None, "--instructions", "-i", help="Guidance to apply for every tweet."
    ),
    node_path: str = typer.Option("node", "--node-path", help="Path to Node.js binary."),
    min_minutes: float = typer.Option(60.0, "--min-minutes", help="Minimum minutes between posts."),
    max_minutes: float = typer.Option(60.0, "--max-minutes", help="Maximum minutes between posts."),
    cycles: Optional[int] = typer.Option(None, "--cycles", help="Stop after N posts (default: infinite)."),
) -> None:
    if max_minutes < min_minutes:
        typer.echo("max-minutes must be greater than or equal to min-minutes.", err=True)
        raise typer.Exit(code=1)

    agent = TwitterAgent()
    run_count = 0
    typer.echo("Starting auto-loop poster. Press Ctrl+C to stop.")
    try:
        while True:
            typer.echo(f"\n[{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC] Generating tweet #{run_count + 1}...")
            try:
                tweet = agent.draft_tweet(topic=topic, instructions=instructions)
                typer.echo(tweet)
                post_to_x(tweet_text=tweet, node_bin=node_path)
                typer.echo("Tweet posted to X.")
            except Exception as exc:
                typer.echo(f"Cycle failed: {exc}", err=True)
            else:
                run_count += 1
                if cycles and run_count >= cycles:
                    typer.echo("Completed requested number of cycles. Exiting.")
                    break

            sleep_minutes = random.uniform(min_minutes, max_minutes)
            sleep_seconds = sleep_minutes * 60
            typer.echo(f"Sleeping for {sleep_minutes:.2f} minutes.")
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        typer.echo("\nAuto-loop interrupted by user.")


@app.command("history")
def history(
    limit: int = typer.Option(10, "--limit", help="Number of stored tweets to display."),
) -> None:
    with db.session_scope() as session:
        query = session.query(db.TweetRecord).order_by(db.TweetRecord.created_at.desc()).limit(limit)
        tweets = list(query.all())

    if not tweets:
        typer.echo("No tweets have been drafted yet.")
        return

    for record in tweets:
        typer.echo(f"[{record.created_at:%Y-%m-%d %H:%M}] ({record.topic or 'general'}) {record.content}")


def main(argv: Optional[list[str]] = None) -> None:
    app(prog_name="twitter-agent", standalone_mode=False, args=argv)


if __name__ == "__main__":
    main(sys.argv[1:])
