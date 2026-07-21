# Adaptive Responsible AI Interview Agent

A Google ADK proof of concept that transforms a fixed 88-question Responsible AI checklist into a project-specific, traceable interview.

The agent reviews a structured AI project profile, determines which checklist questions apply, and creates an applicability plan before beginning the interview. During the interview, only the selected questions are presented to the user.

## Project status


The current version demonstrates:

* LLM-driven applicability decisions across all 88 checklist questions
* Lifecycle-based batching during the planning stage
* Project-specific question selection
* Automatic skipping of irrelevant questions
* Extraction of answers already present in the project profile
* One-question-at-a-time interview delivery
* Structured answer persistence
* Decision and interview tracing
* Separation of LLM reasoning from deterministic Python responsibilities


---

## Problem

A traditional Responsible AI intake process may present every project with the same checklist, even when large portions do not apply.

For example, a classical machine-learning project may still receive questions about:

* Prompt injection
* Hallucinations
* Generative text
* Foundation models
* Retrieval-augmented generation
* External user interactions

This creates unnecessary work and can make the review process feel repetitive or disconnected from the project being assessed.

The goal of this proof of concept is to create an adaptive interview that:

1. Reviews every checklist question.
2. Determines whether each question applies to the project.
3. Skips questions that are genuinely irrelevant.
4. Reuses information already available in the project profile.
5. Presents only the selected questions during the interview.
6. Preserves a trace explaining every decision.

---

## How it works

The system separates applicability planning from the user-facing interview.

### 1. Project profile

The process begins with a structured project profile containing facts such as:

* Project and model type
* Current lifecycle stage
* Whether the project uses generative AI or an LLM
* Whether it uses information retrieval
* Whether it trains a model from scratch
* Whether it uses a third-party or pretrained model
* Whether it uses personal or sensitive data
* Whether it interacts with external users
* Whether it makes or supports decisions
* Whether human oversight is required
* The type of output produced

A value of `false` means the profile explicitly establishes that the capability is not used.

A value of `null` means the information is currently unknown.

### 2. Applicability planning

The 88 checklist questions are divided into lifecycle-phase batches.

For each planning call, the applicability model receives:

* The complete structured project profile
* One lifecycle-phase batch
* The full wording of each question
* Any subquestions
* Question metadata

The model returns a structured decision for every question in the batch.

Supported decisions include:

| Decision                | Meaning                                                                   |
| ----------------------- | ------------------------------------------------------------------------- |
| `ask`                   | The question applies and still requires an answer                         |
| `skip`                  | The question is genuinely irrelevant to the project                       |
| `answered_from_project` | The question applies, but the project profile already contains the answer |
| `needs_clarification`   | A missing project fact determines applicability                           |
| `manual_review`         | The question cannot be classified safely without human review             |

Python validates each batch and combines the decisions into one applicability plan covering all 88 questions.

### 3. Adaptive interview

Once planning is complete, the interview agent reads from the applicability plan.

The interview does not reload or reconsider all 88 questions on every user turn.

Instead, it:

1. Retrieves the next selected question.
2. Presents one item to the user.
3. Records the response.
4. Moves to the next applicable question.
5. Finishes when the interview queue is empty.

Questions classified as `skip` do not enter the user-facing interview.

Questions classified as `answered_from_project` are recorded without asking the user again.

### 4. Decision trace

The system records structured events including:

* `applicability_decision`
* `applicability_plan_created`
* `answer_extracted_from_project`
* `question_selected`
* `answer_received`
* `interview_answer_recorded`
* `interview_completed`

The trace allows a reviewer to reconstruct why a question was asked, skipped, or answered automatically.

---

## Architecture and design principles

The project follows a deliberate separation of responsibilities.

### The LLM is responsible for

* Understanding the project context
* Interpreting the intent of checklist questions
* Determining applicability
* Recognizing when only part of a compound question applies
* Generating decision reasons
* Identifying relevant project evidence
* Conducting the interview

### Python is responsible for

* Loading the question database
* Validating structured model output
* Confirming all expected question IDs are returned
* Preventing duplicate decisions
* Combining lifecycle batches
* Maintaining session state
* Persisting answers
* Recording trace events
* Managing the interview queue

Python does not use question-ID-specific applicability rules to force particular decisions.

This keeps semantic applicability reasoning with the LLM while retaining deterministic validation and persistence.

---

## Context strategy

The complete 88-question checklist is not loaded on every interview turn.

During planning, questions are partitioned by lifecycle phase. Each planning call receives the full project profile and only the questions in that phase.

The results are then compressed into a structured applicability plan.

This approach can be described as:

> Semantic context partitioning by lifecycle phase, followed by context compression into a structured applicability plan.

The broader architecture can also be described as:

> Structured, tool-mediated context construction with selective context filtering and stateful refinement.

This is not a retrieval-augmented generation system. The checklist is a controlled structured dataset rather than a document corpus retrieved through semantic search.

---

## Example project profile

The primary test project is a housing-price prediction model using supervised classical machine learning.

Important project characteristics include:

```json
{
  "project_name": "Housing Price Prediction Model",
  "project_type": "classical_ml",
  "uses_classical_ml": true,
  "uses_generative_ai": false,
  "uses_llm": false,
  "uses_information_retrieval": false,
  "trains_model": true,
  "trains_model_from_scratch": true,
  "uses_third_party_model": false,
  "uses_external_pretrained_model": false,
  "uses_personal_data": false,
  "externally_facing": false,
  "interacts_with_end_users": false,
  "makes_or_supports_decisions": true,
  "requires_human_oversight": true,
  "lifecycle_status": "development",
  "output_type": "numeric_prediction",
  "generates_free_text": false
}
```

This profile is used to test whether the planner can distinguish general Responsible AI requirements from controls that are specific to generative AI, retrieval systems, personal-data processing, or external user interactions.

---

## Examples of adaptive decisions

### Generative-AI questions

Questions specifically concerning prompts, hallucinations, or generated free text can be skipped because the example project does not use generative AI.

### Information-retrieval questions

Questions about retrieval relevance or grounding can be skipped because the project does not contain an information-retrieval component.

### Third-party-model questions

Vendor and externally supplied model questions can be skipped because the project trains its own model rather than using a third-party pretrained model.

Using open-source software does not automatically mean that the project uses a third-party model.

### Answers extracted from the profile

When the project profile already establishes that the problem is being solved without generative AI, the system can record that answer directly rather than asking the user again.

---

## Repository structure

```text
checklist_agent/
├── agent/
│   ├── __init__.py
│   ├── agent.py
│   ├── instructions.py
│   └── intake_agent.py
├── data/
│   ├── mock_questions.json
│   ├── project_profile.json
|   ├── decision_trace.jsonl
│   └── user_responses.json
├── docs/
│   ├── ai_guidelines_database_schema.md
│   └── project_notes.md
├── schema/
│   ├── __init__.py
│   └── applicability.py
├── tests/
│   ├── test_intake_agent.py
│   ├── test_interview_plan.py
│   ├── test_question_loader.py
│   └── test_response_store.py
├── tools/
│   ├── __init__.py
│   ├── applicability_engine.py
│   ├── decision_trace.py
│   ├── interview_plan.py
│   ├── question_loader.py
│   └── response_store.py
├── config.py
├── main.py
├── requirements.txt
└── README.md
```

Runtime-generated files such as session databases, traces, responses, cache directories, and environment files are excluded from version control.

---

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd checklist_agent
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root.

For example:

```env
GOOGLE_API_KEY=your_api_key_here
```

Do not commit the `.env` file.

Depending on the selected Google ADK and Gemini configuration, additional environment variables may be required.

---

## Running the project

Run the main application:

```bash
adk run agent 
#or 
adk web
```


The exact command may vary depending on whether the project is being launched directly through Python or through an ADK development interface.

Before starting a new evaluation run, reset or remove any previous runtime-generated state if a clean session is required.

---

## Running tests

Install `pytest` if it is not already included in the project dependencies:

```bash
pip install pytest
```

Run the test suite:

```bash
pytest
```

For more detailed output:

```bash
pytest -v
```

---

## Current evaluation status

The proof of concept has been evaluated through multiple interview runs.

Testing has led to improvements involving:

* Distinguishing open-source software from third-party models
* Correctly retaining classical ML parameter questions
* Correctly retaining adversarial-testing questions
* Removing deterministic applicability overrides
* Grouping duplicate clarification requirements
* Preserving question IDs in stored answers
* Distinguishing skipped questions from questions answered by the project profile
* Recognizing that examples in a question are illustrative rather than exhaustive

The most recent testing has focused on nuanced edge cases such as:

* Proxy variables for protected characteristics
* Planned deployment controls for projects still in development
* Mixed applicability within compound questions
* Maintenance-stage adversarial testing

---

## Known limitations

### Limited project diversity

Most evaluation has used one classical ML housing-price project.

The planner still requires testing with:

* Generative-AI projects
* LLM applications
* Retrieval systems
* Third-party foundation models
* External user-facing systems
* Projects using personal or sensitive data
* High-impact automated decision systems
* Projects that do not train their own models

### Lack of evaluation

Formal evaluation should eventually measure:

* Overall agreement
* False-skip rate
* False-ask rate
* Precision and recall by decision type
* Stability across repeated runs

### Partial subquestion applicability

The planner can recognize that one subquestion applies while another does not.

The current schema still generally stores one decision for the complete checklist item rather than formally identifying applicable subquestions.

### Confidence calibration

Confidence values are not yet meaningfully calibrated and should not currently be interpreted as formal probabilities.


### Answer-quality evaluation

The current evaluation primarily focuses on applicability planning instead of assessing
whether the user's answer is sufficiently detailed or accurate.


---

## Planned next steps

Potential next steps include:

1. Finalize lifecycle-aware applicability guidance.
2. Test the planner against a diverse set of AI project profiles.
3. Add a few questions to account for a lackluster project profile.
4. Improve confidence calibration.
5. Uploading supporting project documents.
6. Add a persisting session
7. Export completed answers into the required review spreadsheet or reporting format.


---

## Proof-of-concept success criteria

The proof of concept is considered successful when it demonstrates that:

* All 88 checklist questions are reviewed.
* Applicability decisions are made by the LLM.
* Clearly irrelevant questions are removed from the user-facing interview.
* Applicable classical ML controls remain present.
* Existing project facts can answer questions automatically.
* The interview presents one selected item at a time.
* Decisions and answers are auditable through the trace.
* Python validates and persists the workflow without forcing semantic decisions.

---

