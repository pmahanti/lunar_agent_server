# Lunar Geology Agent

A web-based AI agent that generates scientifically rigorous geologic 
briefings for any lunar location given coordinates (lat, lon).

## Features
- Chains 6 simulated Python tools from the Lunar Geology Skill Library
- Identifies named features: swirls, domes, rilles, scarps, vents
- Returns structured briefings covering geomorphology, stratigraphy, 
  spectral mineralogy, topography, and key researchers

## Usage
Enter coordinates as `lat, lon` (e.g. `7.37, -59.02` for Reiner Gamma)
and click **Run agent**.

## Preset locations
- Reiner Gamma swirl
- Cobra Head vent (Vallis Schroteri)
- Apollo 11 landing site
- Tycho crater
- Mare Imbrium
- Aristarchus plateau

## Deployment
Hosted on Railway. Backend: Python/Flask. AI: Anthropic Claude Sonnet.
