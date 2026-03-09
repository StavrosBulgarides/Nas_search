NAS File Index and Search Tool
Full Product & Technical Specification
1. Overview
Purpose

The tool provides fast, intelligent search and navigation for files stored on a Synology NAS.

The built-in Synology Universal Search is limited because:

results cannot easily be restricted by folder

search can be slow

results are not prioritised based on user context

file management actions such as rename are not integrated

This system solves those problems by creating a dedicated searchable metadata index of NAS files and providing a web interface optimised for structured search.

2. Key Goals

The system should allow users to:

Search files quickly

Narrow searches to specific folders

Find files using partial memory (e.g. folder name + keyword)

Rename files easily

Discover recently used files

Optionally use fuzzy search if exact matches fail

Performance target:

Search results under 100ms
3. System Architecture

The system consists of four main components.

NAS Storage
     │
     ▼
Indexing Service
     │
     ▼
Metadata Database
     │
     ▼
Search API
     │
     ▼
Web User Interface
4. Components
4.1 Indexing Service

Responsible for:

scanning NAS folders

extracting file metadata

updating the database

detecting file changes

Runs:

Nightly scheduled job

Default time:

02:00

Manual indexing should also be available.

4.2 Metadata Database

Stores indexed file data for rapid searching.

Recommended options:

Option A (preferred)
SQLite + FTS5

Advantages:

extremely fast

no server required

simple deployment

Suitable for:

<1 million files
Option B
PostgreSQL

Better if:

multi-user environment

very large file collections

4.3 Search API

Backend service that:

receives search queries

runs database queries

applies ranking logic

returns results to the UI

Recommended frameworks:

Python:

FastAPI

or

Node.js:

Express
4.4 Web Interface

Browser-based interface providing:

search box

folder filters

results view

file rename capability

Recommended framework:

React

or

Vue
5. Data Model

Each indexed file record contains:

Field	Description
id	unique identifier
filename	name of file
folder_path	directory path
full_path	full file location
extension	file extension
size	file size
created_date	creation date
modified_date	last modified date
indexed_date	timestamp of last indexing
checksum (optional)	used for duplicate detection
6. Indexing System
6.1 Initial Index

The system performs a full scan when first deployed.

Process:

1. Traverse configured root directories
2. Collect metadata
3. Insert records into database
6.2 Nightly Incremental Scan

Nightly scan performs:

Insert new files
Update modified files
Delete missing files

Optimisation:

Use directory modification timestamps to avoid scanning unchanged folders.

6.3 Indexing Performance

Typical times:

File Count	Scan Time
50k files	<1 minute
250k files	2–5 minutes
1M files	~10 minutes
7. Search Functionality
7.1 Default Search Behaviour

Default search:

case-insensitive

partial filename match

exact matching prioritised

Example:

Search:

contract

Returns:

contract_final.pdf
client_contract_draft.docx
7.2 Instant Type-Ahead Search

Search runs automatically while typing.

Behaviour:

300ms delay after typing

Initial results:

20 items

Pressing Enter:

full results page
7.3 Fuzzy Search

Fuzzy search tolerates spelling errors.

Example:

contrcat

Matches:

contract_final.pdf

Implementation:

Levenshtein distance

Default:

OFF

User can enable via checkbox.

If no results are found:

UI suggests enabling fuzzy search.

8. Natural Language / Folder-Aware Search

Users often remember context rather than filenames.

Search queries should automatically consider:

folder names
file names

Example:

Search:

acme contract

System interprets:

folder contains: acme
filename contains: contract
Query Parsing

Steps:

1. Split search query into tokens
2. Apply tokens to filename and folder path
3. rank results by relevance
9. Folder Filtering

Users can restrict search to specific directories.

Methods:

Folder dropdown
Folder: [All folders ▼]
Folder tree navigation

Sidebar structure:

/
 ├ Clients
 │   ├ ACME
 │   └ BetaCorp
 ├ Accounts
 └ Archive

Selecting a folder restricts search scope.

10. Result Ranking

Results ranked using weighted scoring.

Example formula:

score =
filename_match_weight
+ folder_match_weight
+ folder_usage_weight
+ recency_weight

Suggested weights:

Factor	Weight
Filename match	10
Folder match	5
Folder usage	5
Recent modification	3
11. Folder Usage Weighting

The system tracks which folders users frequently search.

This allows commonly used folders to rank higher.

Data stored:

folder_usage
-------------
folder_path
usage_count
last_accessed
12. Search Results Display

Results table:

| Filename | Folder | Size | Modified | Actions |

Example:

contract_final.pdf
/clients/acme
2.3MB
Modified: 14 Jan 2025
[Open] [Rename]
13. File Rename Feature

Users can rename files directly from the interface.

Workflow
User clicks Rename
Edit field appears
User enters new name
Validation runs
Rename command executed on NAS
Database updated
Validation Rules

Reject:

invalid characters

duplicate filename in folder

empty filename

14. Recent Files Panel

Displays recently modified files.

Query:

ORDER BY modified_date DESC
LIMIT 10

Example display:

Recent Files
-------------
contract_acme.pdf
tax_summary_2023.xlsx
meeting_notes.docx
15. Folder Shortcuts

Users can pin frequently used folders.

Example:

Pinned folders
---------------
Clients
Accounts
Projects
16. User Interface Layout

Recommended interface:

------------------------------------------------
Search files...

[ ] Enable fuzzy search
Folder: [All folders ▼]

------------------------------------------------
Pinned folders
Clients
Accounts
Projects

------------------------------------------------
Recent files
contract_acme.pdf
tax_summary_2023.xlsx

------------------------------------------------
Search Results
------------------------------------------------
Filename | Folder | Size | Modified | Actions
------------------------------------------------
17. Performance Requirements

Target speeds:

Action	Target
Search query	<100ms
Instant search response	<200ms
Rename operation	<1s
18. Logging

System should log:

Indexing runs
Search queries
Rename actions
Errors
19. Security

Basic security measures:

restrict rename operations to authorised users

avoid executing arbitrary file paths

log all write operations

Optional:

User authentication
20. Deployment

Recommended deployment:

Docker containers on Synology NAS

Services:

Container 1: Indexing service
Container 2: API server
Container 3: Web UI
Container 4: Database
21. Configuration

Admin configuration options:

Setting	Description
Indexed root folders	which NAS directories to index
Scan schedule	nightly index time
Max results	search result limit
Fuzzy search default	on/off
22. Future Enhancements

Potential future capabilities:

Content Indexing

Search inside:

PDF
Word
Text files
File Tagging

Users can attach tags to files:

#tax
#client-acme
#legal
Duplicate File Detection

Using file checksums.

AI-Assisted Search

Natural language queries:

"contracts with ACME from 2022"
23. Expected Scale

Supported scale:

Files	Performance
10k	instant
100k	<1s
1M	1–2s
24. Estimated Development Effort
Feature	Estimated Time
Core indexing system	4–6 days
Search API	3–4 days
Web UI	5–7 days
Rename feature	1 day
Fuzzy search	1 day
Folder weighting	2 days

Total MVP:

2–3 weeks development