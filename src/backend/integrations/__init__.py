"""Integrated external services (server side only): Kakao, TourAPI, NAVER, KMA, AirKorea
and AWS Bedrock, plus `factory` that wires them into `tools.Providers`. Each returns plain
dicts in the shapes `tools.Providers` expects; failures raise and are recorded by `tools.guarded`."""
