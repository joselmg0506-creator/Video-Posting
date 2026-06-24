"""
Content producers — the "front-half" of each channel.

A producer takes a channel config + the global config and returns a list of ready-to-post
`PostItem`s (already rendered 9:16 with captions). The shared "back-half" (posting,
state, dedup) lives in main.py. One producer per content_type:

  clips         -> main.produce_clips (Twitch/YouTube streamer clips)
  reddit_story  -> producers.reddit_story (AI TTS over gameplay b-roll)
  ai_character  -> producers.ai_character (Flux character art + lore, built last)
"""
