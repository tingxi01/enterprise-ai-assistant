
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


API_URL = "http://127.0.0.1:8002"

ROOT = Path(__file__).resolve().parent.parent

TEST_CASES = ROOT / "tests" / "rag_eval_cases.json"
REPORT_PATH = ROOT / "reports" / "rag_eval_results.json"

ABSTAIN_TEXT = "i couldn't find that information in the document"

TOP_K = 5


def get_test_documents():
    """Find the uploaded PDFs needed for evaluation."""

    response = requests.get(
        f"{API_URL}/documents",
        timeout=30,
    )
    response.raise_for_status()

    documents = response.json()["documents"]
    document_map = {}

    for doc in documents:
        filename = doc["filename"].lower()

        if filename in document_map:
            raise RuntimeError(
                f"Multiple copies of {doc['filename']} exist. "
                "Keep one copy before evaluation."
            )

        document_map[filename] = doc

    return document_map


def check_required_facts(answer, case):
    """Check expected facts and keywords."""

    found = []
    missing = []

    for label, pattern in case.get(
        "required_facts", {}
    ).items():
        if re.search(
            pattern,
            answer,
            flags=re.IGNORECASE,
        ):
            found.append(label)
        else:
            missing.append(label)

    normalized = answer.lower()

    # Compatibility with original ORANGE.pdf test cases.
    for keyword in case.get("expected_keywords", []):
        if keyword.lower() in normalized:
            found.append(keyword)
        else:
            missing.append(keyword)

    return found, missing


def check_forbidden_patterns(answer, case):
    """Detect known incorrect statements."""

    violations = []

    for label, pattern in case.get(
        "forbidden_patterns", {}
    ).items():
        if re.search(
            pattern,
            answer,
            flags=re.IGNORECASE,
        ):
            violations.append(label)

    return violations


def check_step_order(answer, case):
    """
    Check whether required procedural actions appear in order.

    This is a basic text-order check, not a complete semantic
    evaluation. It uses the first occurrence of each keyword.
    """

    expected_order = case.get(
        "required_step_order", []
    )

    if not expected_order:
        return True, [], []

    positions = []
    missing_steps = []

    for step in expected_order:
        match = re.search(
            re.escape(step),
            answer,
            flags=re.IGNORECASE,
        )

        if match:
            positions.append(match.start())
        else:
            positions.append(-1)
            missing_steps.append(step)

    step_order_valid = (
        not missing_steps
        and positions == sorted(positions)
        and len(set(positions)) == len(positions)
    )

    return step_order_valid, positions, missing_steps


def evaluate_case(case, document):
    """Evaluate one RAG question against its assigned PDF."""

    document_id = document["id"]

    response = requests.post(
        f"{API_URL}/documents/ask",
        json={
            "question": case["question"],
            "top_k": TOP_K,
            "document_id": document_id,
        },
        timeout=240,
    )
    response.raise_for_status()

    data = response.json()

    answer = data.get("answer", "").strip()
    sources = data.get("sources", [])

    should_abstain = case.get(
        "should_abstain", False
    )

    abstained = ABSTAIN_TEXT in answer.lower()

    found_facts, missing_facts = check_required_facts(
        answer,
        case,
    )

    violations = check_forbidden_patterns(
        answer,
        case,
    )

    (
        step_order_valid,
        step_positions,
        missing_steps,
    ) = check_step_order(
        answer,
        case,
    )

    # Check that every retrieved chunk belongs to this PDF.
    sources_valid = (
        len(sources) > 0
        and all(
            str(source.get("document_id"))
            == str(document_id)
            for source in sources
        )
    )

    # Extract citations in the form [Source 1], etc.
    citation_numbers = [
        int(number)
        for number in re.findall(
            r"\[Source\s+(\d+)\]",
            answer,
            flags=re.IGNORECASE,
        )
    ]

    # A valid citation must refer to one of the
    # retrieved chunks.
    citations_valid = (
        len(citation_numbers) > 0
        and all(
            1 <= number <= len(sources)
            for number in citation_numbers
        )
    )

    if should_abstain:
        # A source citation is not required for refusals.
        passed = (
            abstained
            and sources_valid
            and not violations
        )
    else:
        passed = (
            bool(answer)
            and not abstained
            and not missing_facts
            and not violations
            and sources_valid
            and citations_valid
            and step_order_valid
        )

    failure_reasons = []

    if not answer:
        failure_reasons.append(
            "Empty answer"
        )

    if should_abstain and not abstained:
        failure_reasons.append(
            "Did not abstain"
        )

    if not should_abstain and abstained:
        failure_reasons.append(
            "Unexpected refusal or contradictory abstention"
        )

    if missing_facts:
        failure_reasons.append(
            "Missing facts: "
            + ", ".join(missing_facts)
        )

    if violations:
        failure_reasons.append(
            "Forbidden statements: "
            + ", ".join(violations)
        )

    if not step_order_valid:
        failure_reasons.append(
            "Procedural steps are missing or out of order"
        )

        if missing_steps:
            failure_reasons.append(
                "Missing steps: "
                + ", ".join(missing_steps)
            )

    if not sources_valid:
        failure_reasons.append(
            "Missing sources or incorrect source document"
        )

    if (
        not should_abstain
        and not citations_valid
    ):
        failure_reasons.append(
            "Missing or invalid [Source N] citations"
        )

    return {
        "id": case["id"],
        "document": document["filename"],
        "question": case["question"],
        "passed": passed,
        "should_abstain": should_abstain,
        "abstained": abstained,
        "found_facts": found_facts,
        "missing_facts": missing_facts,
        "forbidden_violations": violations,
        "step_order_valid": step_order_valid,
        "step_positions": step_positions,
        "missing_steps": missing_steps,
        "sources_valid": sources_valid,
        "citations_valid": citations_valid,
        "citation_numbers": citation_numbers,
        "source_count": len(sources),
        "model": data.get("model"),
        "failure_reasons": failure_reasons,
        "answer": answer,
    }


def main():
    try:
        cases = json.loads(
            TEST_CASES.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(cases, list) or not cases:
            raise ValueError(
                "Evaluation file must contain "
                "a non-empty JSON array."
            )

        documents = get_test_documents()

        required_documents = {
            case["document"].lower()
            for case in cases
        }

        missing_documents = (
            required_documents
            - set(documents.keys())
        )

        if missing_documents:
            raise RuntimeError(
                "Upload the missing PDF(s): "
                + ", ".join(
                    sorted(missing_documents)
                )
            )

        print(
            "\nENTERPRISE AI — RAG EVALUATION"
        )
        print("=" * 50)
        print(f"Test cases: {len(cases)}")
        print(
            f"Retrieval depth: top_k={TOP_K}"
        )
        print(
            "Documents: "
            + ", ".join(
                sorted(required_documents)
            )
        )

        results = []

        for index, case in enumerate(
            cases,
            start=1,
        ):
            print(
                f"\n[{index}/{len(cases)}] "
                f"{case['id']} "
                f"({case['document']})",
                flush=True,
            )

            document = documents[
                case["document"].lower()
            ]

            try:
                result = evaluate_case(
                    case,
                    document,
                )

            except (
                requests.RequestException,
                ValueError,
                KeyError,
                TypeError,
                re.error,
            ) as exc:
                result = {
                    "id": case["id"],
                    "document": case["document"],
                    "question": case["question"],
                    "passed": False,
                    "error": str(exc),
                    "failure_reasons": [
                        f"Evaluation error: {exc}"
                    ],
                }

            results.append(result)

            status = (
                "PASS"
                if result["passed"]
                else "FAIL"
            )

            print(
                f"  Result: {status}",
                flush=True,
            )

            for reason in result.get(
                "failure_reasons",
                [],
            ):
                print(
                    f"  - {reason}",
                    flush=True,
                )

            if "answer" in result:
                preview = (
                    result["answer"]
                    .replace("\n", " ")
                    [:220]
                )

                print(
                    f"  Answer: {preview}",
                    flush=True,
                )

        total = len(results)

        passed_count = sum(
            result["passed"]
            for result in results
        )

        failed_count = (
            total - passed_count
        )

        pass_rate = round(
            passed_count / total * 100,
            1,
        )

        # Calculate results separately for each PDF.
        by_document = {}

        for result in results:
            filename = result["document"]

            if filename not in by_document:
                by_document[filename] = {
                    "total": 0,
                    "passed": 0,
                }

            by_document[filename]["total"] += 1

            if result["passed"]:
                by_document[filename]["passed"] += 1

        for filename, counts in by_document.items():
            counts["pass_rate"] = round(
                counts["passed"]
                / counts["total"]
                * 100,
                1,
            )

        report = {
            "evaluated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "top_k": TOP_K,
            "total_cases": total,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": pass_rate,
            "by_document": by_document,
            "results": results,
        }

        REPORT_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        REPORT_PATH.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            "\n" + "=" * 50
        )
        print(
            "EVALUATION SUMMARY"
        )
        print("=" * 50)

        print(
            f"Passed: {passed_count}/{total}"
        )
        print(
            f"Failed: {failed_count}"
        )
        print(
            f"Pass rate: {pass_rate}%"
        )

        for filename, counts in by_document.items():
            print(
                f"{filename}: "
                f"{counts['passed']}/"
                f"{counts['total']} "
                f"({counts['pass_rate']}%)"
            )

        print(
            f"\nReport saved: {REPORT_PATH}"
        )

        if failed_count > 0:
            sys.exit(1)

    except (
        requests.RequestException,
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(
            f"\nEvaluation error: {exc}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
