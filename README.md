# Transparent — Distributed Social Network Node

## Overview
Transparent is a simplified distributed social networking platform built for CMPUT 404. It follows a decentralized, peer-to-peer model inspired by early federated systems such as Diaspora and modern protocols like ActivityPub, but intentionally reduces complexity for educational purposes.

Each instance (node) operates independently while supporting federation with other nodes. Users can create content locally and share it across the network through a push-based inbox model.

## Key Ideas
- **Decentralization:** No single platform owns the network. Users can host or join any node.
- **Federation:** Nodes communicate with each other to share content.
- **Inbox Model:** Content is pushed to followers across nodes rather than pulled.
- **Simplicity First:** Designed to be RESTful and minimal, avoiding the complexity of full ActivityPub compliance.
- **Content Aggregation:** Authors can view posts from users they follow across different nodes.
- **External Integration:** Supports importing content from external sources (e.g., GitHub).

---

## Group Members
1. Abdulkadar Taheri Zaveri  
2. Ali Anish  
3. Animesh Mittal  
4. Anurag Jain  
5. Arsalan Ahmed  
6. Krupal Shah  

---

## Project Purpose
This repository implements a distributed social network node with:
- Local social features (profiles, follows, posts, comments, likes)
- Federation support for interacting with remote nodes
- Inbox-based communication for distributing content

---

## Collaboration Requirement
This project is designed to interoperate with **at least 3 other groups' nodes**. Ensure compatibility by:
- Following agreed API formats
- Testing cross-node inbox delivery
- Supporting foreign authors and content

---

## Architecture Overview

### Core Components
- `transparent/authors/` — Author profiles and follow system
- `transparent/entries/` — Posts and visibility handling
- `transparent/interactions/` — Comments and likes
- `transparent/inbox/` — Federation inbox (core of distributed sharing)
- `transparent/nodes/` — Remote node configuration
- `transparent/social/` — Follow relationships
- `transparent/core/` — Utilities (auth, pagination, identifiers)
- `transparent/config/` — Django configuration

---

## Federation Model
- Nodes communicate via REST APIs
- Content is sent directly to follower inboxes
- Remote authors are treated similarly to local authors
- No heavy cryptography or protocol overhead

---

## API Documentation
See: [DOCUMENTATION.md](DOCUMENTATION.md)

Includes:
- Endpoint definitions
- Request/response formats
- Federation payload structure

---

## Local Development

### Setup
```bash
pip install -r requirements.txt
```

### Run Server
```bash
python transparent/manage.py migrate
python transparent/manage.py runserver
```

### Access
- UI: http://127.0.0.1:8000/stream/
- API: http://127.0.0.1:8000/api/authors/

## Design Philosophy
- Minimalist federation (no full ActivityPub implementation)
- Readable and maintainable code
- Focus on learning distributed systems concepts
- Trade-offs favor simplicity over production-grade security

## Copyright
© The following contributors:

1. Abdulkadar Taheri Zaveri  
2. Ali Anish  
3. Animesh Mittal  
4. Anurag Jain  
5. Arsalan Ahmed  
6. Krupal Shah  

## Acknowledgements
- Inspired by decentralized platforms like Diaspora
- Concepts influenced by ActivityPub (W3C)
- Built as part of CMPUT 404 (Distributed Systems)

## Future Improvements
- Stronger authentication between nodes  
- Optional encryption for federation  
- Partial compatibility with ActivityPub  
- Improved UI/UX  
- Real-time updates (e.g., WebSockets)  
- Better interoperability with external nodes  

## Contributing
This project is primarily for academic purposes, but contributions are welcome.

If you wish to contribute:
1. Fork the repository  
2. Create a feature branch  
3. Submit a pull request with clear documentation  

## Disclaimer
This project is a simplified academic implementation of a distributed social network.  
It is **not production-ready** and does not include robust security or scalability guarantees.
