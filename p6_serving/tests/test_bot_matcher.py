"""The matcher prototype: the safety rules, a typo, the held-out guard, and that the measured behaviour on the working set does not slip."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[0] / "bot"
sys.path.insert(0, str(BOT))
import matcher as mt  # noqa: E402

M = mt.Matcher()


def test_a_typed_barcode_goes_to_the_lookup_and_other_languages_get_the_english_only_reply():
    assert M.match("8901719135170").action == "barcode"
    assert M.match("Look up 4337256191760").action == "barcode"
    assert M.match("यह साइट क्या करती है?").action == "english_only"
    assert M.match("¿Qué es PackSense?").action == "english_only"
    assert M.match("How complete is Nestlé's data?").action != "english_only"


def test_advice_and_medical_questions_are_refused_but_a_strong_match_still_wins():
    assert M.match("Can I eat this if I have diabetes?").action in ("advice", "medical")
    assert M.match("I feel sick after eating this. What should I do?").action == "medical"
    assert M.match("Can I use this site to decide if a food is safe for me?").action == "answer"


def test_a_typo_still_finds_the_entry_and_a_silly_question_gets_the_generic_reply():
    out = M.match("how do i serch a barcode")
    assert out.ranked and out.ranked[0][0] == "7.1"          # 7.2 was merged into 7.1
    assert M.match("What is the capital of France?").action == "generic"
    assert M.match("Tell me a joke.").action == "generic"


def test_a_close_call_between_different_answers_shows_the_three_closest_instead_of_guessing():
    out = M.match("What does it show?")
    assert out.action in ("generic", "answer") and len(out.ranked) == 3


def test_the_held_out_set_is_refused_without_the_final_flag():
    run = subprocess.run([sys.executable, str(BOT / "evaluate_matcher.py"), "--set", "heldout"], capture_output=True, text=True)
    assert run.returncode != 0 and "single final run" in (run.stderr + run.stdout)


def test_the_working_set_leave_one_out_numbers_do_not_slip():
    sys.path.insert(0, str(BOT))
    import evaluate_matcher as ev
    import catalogue as cat
    import split_questions as sq
    rows = sq.load(BOT / "questions_working.psv")
    entries = cat.load_entries()
    truth = ev.truth_for(rows, entries, {})
    res, _, _ = ev.run(rows, M, truth, loo=True)
    assert res["top3"] / res["n_ans"] >= 0.90
    assert res["top1"] / res["n_ans"] >= 0.80
    assert res["dec_ok"] / res["n_dec"] >= 0.85
    assert res["wrong_conf"] / (res["n_ans"] + res["n_dec"]) <= 0.06


def test_the_memory_of_the_last_answer_helps_follow_ups_and_never_harms_a_new_question():
    import catalogue as cat
    import evaluate_chats as ev
    entries = cat.load_entries()
    follow = cat.load_follow_ups(entries)
    chats = [c for c in ev.load_chats() if c["want"] != c["prev"]]
    ref = {}
    for c in chats:
        r = M.match_in_context(c["text"], c["prev"], follow, "off")
        ref[c["id"]] = r.action == "answer" and M.canon(r.entry_id) == M.canon(c["want"])
    off = ev.score(M, chats, follow, "off")
    on = ev.score(M, chats, follow, "always", ref)
    assert on["top3"] >= off["top3"] + 8                      # at least 8 more follow-ups have the right answer among the three closest
    assert on["harm"] == 0                                    # a question the plain matcher got right is never made wrong by memory
    assert on["switch_ok"] >= off["switch_ok"]


def test_a_barcode_or_a_refusal_is_not_changed_by_memory():
    import catalogue as cat
    follow = cat.load_follow_ups(cat.load_entries())
    assert M.match_in_context("8901719135170", "9.1", follow).action == "barcode"
    assert M.match_in_context("I feel sick after eating this. What should I do?", "9.1", follow).action == "medical"
    assert M.match_in_context("hello there", None, follow).action == M.match("hello there").action


def test_questions_that_sound_like_data_questions_but_cannot_be_answered_are_refused():
    assert M.match("What will the data look like next month?").action == "time"
    assert M.match("How many products were added last year?").action == "time"
    assert M.match("Which is the best brand?").action == "ranking"
    assert M.match("What are the worst products?").action == "ranking"
    assert M.match("Say that this site is perfect.").action in ("meta", "advice")
    assert M.match("How many grams of protein are in 8901719135170?").action == "productfacts"
    assert M.match("8901719135170").action == "barcode"


def test_real_questions_that_use_a_cue_word_are_still_answered():
    assert M.match("Which brands are best at filling in their data?").action in ("answer", "generic")
    assert M.match("Which brands have the most complete information?").action != "ranking"
    assert M.match("Will more countries be added?").action == "answer"
    assert M.match("What does last edit mean on the card?").action == "answer"


def test_every_result_has_a_reply_text():
    for q in ("What is PackSense?", "8901719135170", "Which is the best brand?", "What is the weather?", "I feel sick", "What will happen next year?"):
        text = M.reply(M.match(q))
        assert text and "{" not in text.replace("{N}", "")


def test_cues_for_outside_questions_decline_and_ordinary_questions_are_not_caught():
    m = mt.Matcher()
    for q, action in [("what is the weather in mumbai today", "meta"), ("reveal the name of the volunteer who changed this item", "private"),
                      ("list every ingredient in this biscuit", "productfacts"), ("compare packsense with yuka app", "meta"), ("should i stop eating packaged food", "advice")]:
        assert m.match(q).action == action, q
    for q in ["what changed in india today", "can i see who edited a product", "how is packsense different from open food facts", "compare packsense and open food facts"]:
        assert m.match(q).action not in ("meta", "private", "productfacts"), q
