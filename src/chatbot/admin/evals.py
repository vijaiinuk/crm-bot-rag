"""Eval run logic: metrics, judge agreement, and the mock judge.

`simulate_results` stands in for real generation + LLM-as-judge (S3.2.1). It is
deterministic per (run, question, persona) so seeded runs and tests are stable.
"""

import random
from collections.abc import Iterable, Sequence

from chatbot.admin.models import (
    EvalMetrics,
    EvalQuestion,
    EvalResult,
    JudgeAgreement,
    Outcome,
)


def simulate_results(run_id: str, questions: Iterable[EvalQuestion]) -> list[EvalResult]:
    results = []
    for q in questions:
        for persona, exp in sorted(q.expected.items()):
            rng = random.Random(f"{run_id}:{q.id}:{persona}")
            actual: Outcome = exp.outcome
            if rng.random() < 0.06:  # the mock pipeline occasionally gets the outcome wrong
                actual = "answer" if exp.outcome != "answer" else "not_found"
            answered = actual == "answer"
            results.append(
                EvalResult(
                    id=f"{run_id}:{q.id}:{persona}",
                    run_id=run_id,
                    question_id=q.id,
                    question=q.question,
                    persona=persona,
                    expected_outcome=exp.outcome,
                    actual_outcome=actual,
                    answer=(
                        f"(Mock answer drawing on {', '.join(exp.required) or 'no sources'}.)"
                        if answered
                        else f"(Mock {actual.replace('_', ' ')} response.)"
                    ),
                    judge_faithful=rng.random() < 0.9 if answered else True,
                    judge_correct=(rng.random() < 0.85 if answered else True)
                    and actual == exp.outcome,
                    citations_ok=rng.random() < 0.92 if answered else True,
                )
            )
    return results


def _ratio(hits: Iterable[bool]) -> float:
    values = list(hits)
    return round(sum(values) / len(values), 4) if values else 1.0


def run_metrics(results: Sequence[EvalResult]) -> EvalMetrics:
    answers = [
        r for r in results if r.expected_outcome == "answer" and r.actual_outcome == "answer"
    ]
    refusals = [r for r in results if r.expected_outcome != "answer"]
    return EvalMetrics(
        faithfulness=_ratio(r.judge_faithful for r in answers),
        correctness=_ratio(r.judge_correct for r in results),
        refusal_accuracy=_ratio(r.actual_outcome == r.expected_outcome for r in refusals),
        citation_accuracy=_ratio(r.citations_ok for r in answers),
    )


def judge_agreement(results: Iterable[EvalResult]) -> JudgeAgreement:
    """How often the LLM judge matches the admins' hand labels."""
    labelled = [r for r in results if r.label is not None]
    if not labelled:
        return JudgeAgreement(labelled=0, faithful_agreement=None, correct_agreement=None)
    return JudgeAgreement(
        labelled=len(labelled),
        faithful_agreement=_ratio(
            r.label.faithful == r.judge_faithful for r in labelled if r.label
        ),
        correct_agreement=_ratio(r.label.correct == r.judge_correct for r in labelled if r.label),
    )
