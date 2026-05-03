"""Utilities and logic for github_utils."""

import requests
from entries.models import Entry

def fetch_and_create_github_entries(author):
    """
    Fetches the latest public GitHub activity for an author and 
    converts new events into public Entry objects.
    """
    # If the author hasn't provided a GitHub URL, skip
    if not author.github:
        return

    # Extract the raw username from the GitHub URL
    username = author.github.rstrip('/').split('/')[-1]
    url = f"https://api.github.com/users/{username}/events/public"
    
    try:
        # Fetch the events with a short timeout so page loads don't hang
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            events = response.json()
            
            # Process only the 5 most recent events to prevent spamming the database
            for event in events[:5]:
                event_id = event.get("id")
                event_type = event.get("type", "Event").replace("Event", "")
                repo_name = event.get("repo", {}).get("name", "a repository")
                
                # We use the description field to store a unique tag for the GitHub event.
                unique_identifier = f"github_event_{event_id}"
                
                # Create the entry only if we haven't seen this specific event before
                if not Entry.objects.filter(author=author, description=unique_identifier).exists():
                    title = f"GitHub Activity: {event_type} on {repo_name}"
                    content = f"I just performed a {event_type} on the repository '{repo_name}' over at GitHub!"
                    
                    Entry.objects.create(
                        author=author,
                        title=title,
                        description=unique_identifier,
                        content=content,
                        content_type="text/plain",
                        visibility="PUBLIC"
                    )
    except requests.exceptions.RequestException:
        # Fail silently if GitHub is down or rate-limiting us
        pass