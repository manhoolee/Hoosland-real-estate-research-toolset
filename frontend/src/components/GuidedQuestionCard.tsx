import { Check, Compass, MagicWand, SkipForward } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import type {
  ClarificationAnswer,
  ClarificationQuestion,
  ClarificationPlan,
} from "../types";

interface GuidedQuestionCardProps {
  plan: ClarificationPlan;
  initialAnswers?: ClarificationAnswer[];
  disabled?: boolean;
  onSubmit: (answers: ClarificationAnswer[]) => void;
  onSkip: () => void;
  onCancel: () => void;
}

type DraftAnswer = {
  optionIds: string[];
  customText: string;
};

function emptyAnswers(plan: ClarificationPlan): Record<string, DraftAnswer> {
  return Object.fromEntries(
    plan.questions.map((question) => [question.id, { optionIds: [], customText: "" }]),
  );
}

function draftFromAnswers(
  plan: ClarificationPlan,
  answers: ClarificationAnswer[] = [],
): Record<string, DraftAnswer> {
  const draft = emptyAnswers(plan);
  for (const answer of answers) {
    if (!draft[answer.questionId]) continue;
    draft[answer.questionId] = {
      optionIds: [...answer.optionIds],
      customText: answer.customText || "",
    };
  }
  return draft;
}

function answerIsComplete(
  question: ClarificationQuestion,
  answer: DraftAnswer | undefined,
): boolean {
  if (!answer) return !question.required;
  return answer.optionIds.length > 0 || answer.customText.trim().length > 0 || !question.required;
}

function toAnswers(
  questions: ClarificationQuestion[],
  draft: Record<string, DraftAnswer>,
): ClarificationAnswer[] {
  return questions.flatMap((question) => {
    const answer = draft[question.id];
    if (!answer) return [];
    const customText = answer.customText.trim();
    if (!answer.optionIds.length && !customText) return [];
    return [{
      questionId: question.id,
      optionIds: answer.optionIds,
      ...(customText ? { customText } : {}),
    }];
  });
}

export function GuidedQuestionCard({
  plan,
  initialAnswers,
  disabled = false,
  onSubmit,
  onSkip,
  onCancel,
}: GuidedQuestionCardProps) {
  const [draft, setDraft] = useState<Record<string, DraftAnswer>>(
    () => draftFromAnswers(plan, initialAnswers),
  );
  const [error, setError] = useState<string | null>(null);

  // A refreshed conversation can replace the plan while this component stays
  // mounted.  Reset local choices only when the server-side plan identity
  // changes; ordinary parent renders should never erase a user's selections.
  useEffect(() => {
    setDraft(draftFromAnswers(plan, initialAnswers));
    setError(null);
  }, [initialAnswers, plan.id, plan.version]);

  const missingQuestion = useMemo(
    () => plan.questions.find((question) => !answerIsComplete(question, draft[question.id])),
    [draft, plan.questions],
  );

  const updateAnswer = (question: ClarificationQuestion, next: Partial<DraftAnswer>) => {
    setDraft((current) => ({
      ...current,
      [question.id]: { ...current[question.id], ...next },
    }));
    setError(null);
  };

  const toggleOption = (question: ClarificationQuestion, optionId: string) => {
    const current = draft[question.id] || { optionIds: [], customText: "" };
    if (question.kind === "single") {
      updateAnswer(question, { optionIds: [optionId] });
      return;
    }
    const optionIds = current.optionIds.includes(optionId)
      ? current.optionIds.filter((id) => id !== optionId)
      : [...current.optionIds, optionId];
    updateAnswer(question, { optionIds });
  };

  const submit = () => {
    if (disabled) return;
    if (missingQuestion) {
      setError(`请先回答“${missingQuestion.prompt}”，也可以填写自定义答案。`);
      return;
    }
    onSubmit(toAnswers(plan.questions, draft));
  };

  return (
    <section
      className="guided-question-card"
      aria-labelledby={`guided-title-${plan.id}`}
      aria-describedby={`guided-description-${plan.id}`}
      aria-busy={disabled}
    >
      <div className="guided-question-heading">
        <span className="guided-question-mark" aria-hidden="true">
          <Compass size={20} weight="regular" />
        </span>
        <div>
          <p className="guided-question-eyebrow">先对齐关键取舍 · {plan.taskTypeLabel}</p>
          <h3 id={`guided-title-${plan.id}`}>{plan.title}</h3>
          <p id={`guided-description-${plan.id}`}>{plan.description}</p>
        </div>
      </div>

      <div className="guided-question-list">
        {plan.questions.map((question, index) => {
          const answer = draft[question.id] || { optionIds: [], customText: "" };
          const inputName = `guided-${plan.id}-${question.id}`;
          return (
            <fieldset className="guided-question" key={question.id}>
              <legend>
                <span className="guided-question-index">{String(index + 1).padStart(2, "0")}</span>
                <span>{question.prompt}</span>
                {question.required ? <em>必选</em> : <small>可选</small>}
              </legend>
              {question.help ? <p className="guided-question-help">{question.help}</p> : null}
              <div className="guided-option-grid">
                {question.options.map((option) => {
                  const checked = answer.optionIds.includes(option.id);
                  return (
                    <label
                      className={`guided-option${checked ? " is-selected" : ""}`}
                      key={option.id}
                    >
                      <input
                        type={question.kind === "single" ? "radio" : "checkbox"}
                        name={inputName}
                        value={option.id}
                        checked={checked}
                        disabled={disabled}
                        aria-label={option.label}
                        onChange={() => toggleOption(question, option.id)}
                      />
                      <span className="guided-option-copy">
                        <span className="guided-option-label">
                          {option.label}
                          {option.recommended ? (
                            <span className="guided-option-recommended">推荐</span>
                          ) : null}
                        </span>
                        <span className="guided-option-impact">{option.impact}</span>
                      </span>
                      <Check className="guided-option-check" size={17} weight="bold" aria-hidden="true" />
                    </label>
                  );
                })}
              </div>
              {question.allowCustom ? (
                <label className="guided-custom-answer">
                  <span>补充你的条件（可选）</span>
                  <textarea
                    aria-label={`${question.prompt}的自定义答案`}
                    value={answer.customText}
                    maxLength={500}
                    rows={2}
                    disabled={disabled}
                    placeholder={question.customPlaceholder || "例如：更看重首开速度，但不能牺牲客户支付力"}
                    onChange={(event) => updateAnswer(question, { customText: event.target.value })}
                  />
                  <small>{answer.customText.length}/500</small>
                </label>
              ) : null}
            </fieldset>
          );
        })}
      </div>

      <p className="guided-question-note">
        <MagicWand size={15} weight="regular" aria-hidden="true" />
        你的选择只会调整本轮分析侧重点；推荐项可以改选，也可以直接执行。
      </p>
      {error ? <p className="guided-question-error" role="alert">{error}</p> : null}
      <div className="guided-question-actions">
        <button type="button" className="guided-cancel-button" disabled={disabled} onClick={onCancel}>
          取消引导
        </button>
        <button type="button" className="guided-skip-button" disabled={disabled} onClick={onSkip}>
          <SkipForward size={16} weight="regular" aria-hidden="true" />
          跳过，直接执行
        </button>
        <button type="button" className="guided-submit-button" disabled={disabled} onClick={submit}>
          <Check size={17} weight="bold" aria-hidden="true" />
          {disabled ? "正在开始" : "确认并开始"}
        </button>
      </div>
    </section>
  );
}
