---
slug: pipeline-health
title: Pipeline health
section: How it works
order: 9
question: Is the system running right now?
built_from: Pipeline health table
design_notes:
  - "A table of jobs and a small chart of run times sit here, followed by the services table."
  - "The Home page's 'Right now' strip reads the same table (pipeline_health, subject 'pipeline')."
---

# Is the system running right now?

PackSense runs by itself every day, with nobody pressing buttons. This page is the status board. It shows each scheduled job, whether its last run worked, how long it takes, and whether the outside services it depends on are answering.

## What this page can and cannot tell you

- A run that did not succeed is counted, whatever the reason. A test we started on purpose looks the same as a real fault.
- It shows the last 90 days.
- It does not show storage size or running costs. We deliberately keep money and usage limits off this site.
- A green board means the jobs ran, not that the data is right.
