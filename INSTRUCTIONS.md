Part A: Run and test the project (about 1 hour)

1. Set up (10 min)

bash
cd worksheet-gen
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-portal.txt

Install Ollama from ollama.com, then:

bash
ollama pull gemma3:4b
ollama list          # confirm it's there

2. Run the automated tests (1 min)

bash
python -m pytest -q

You should see 95 passed. These tests use a mocked model, so they prove the logic works, not that Gemma writes good questions.

3. Run the generator and click through it (20 min)

bash
streamlit run app.py

Check each of these by hand:

Generate a PSLE Math worksheet with one topic, mixed question types and 5 questions. Confirm you see ✅/⚠️/📝 badges.
Replace one question. Expand “Worked solution and mark scheme” on another.
Download the Word file and open it in Word. Check the header, the answer space and the answer key page. Then open the HTML file and print it to PDF.
Add a student in the Students tab. Generate for them and save to history.
Tick two questions as wrong, save the results, then generate again with “Target weak topics” and confirm it picks those topics.
Try one Science and one A-Math sheet. Look for broken formatting in the maths.
Try “Preview as” for both Student and Tutor, and make sure the student view shows no answers.

4. Run the portal and test the hybrid loop (20 min)

Open a second terminal with the same venv:

bash
PORTAL_PUBLIC_URL=http://127.0.0.1:8000 python -m portal.server run
Open http://127.0.0.1:8000, sign up as a tutor, and copy the address and token (the token is shown once).
In Streamlit, open the Portal tab, paste both, and click “Save and test connection”.
Click “Link my students to the portal” and copy a student’s link.
Generate a worksheet, assign it to that student, then open the link in your phone’s browser if it’s on the same Wi-Fi, or in a private window.
Submit answers as the student, then go to the Inbox tab and click “Check for submissions”. Mark it and send it back.
Reload the student link and confirm the score and comment appear.
Confirm the student page never shows an answer key or mark scheme.

5. Run the eval (15–30 min, depends on your laptop)

bash
python eval.py gemma3:4b

This writes eval_results.csv and prints a summary. Copy the numbers into the section 6 table in the README. Then pick about 10 questions per mode, solve them yourself, and record how many were actually correct. Write both numbers in the post, because self-consistency is not correctness.

6. Optional: Docker check (5 min)

bash
docker build -t tutor-portal .
docker run -p 8000:8000 -v portal-data:/data -e PORTAL_PUBLIC_URL=http://127.0.0.1:8000 tutor-portal

Then open http://127.0.0.1:8000/healthz and expect ok.

If anything breaks, write down the error text. A real bug you found and fixed is good material for the post.

Part B: Make sure the submission goes through

Do these first

Push the repo to GitHub as public. Open it in a private window to confirm a stranger can see it. Check that .gitignore excludes *.db, .venv and __pycache__, and that no token or database with student data is committed. Add a licence file; the README says the code is yours to license, so pick one.
Record the demo (2–3 min): generate, a flagged question, replace, export, weak-topic targeting, and assign and mark. Upload it to YouTube (unlisted is fine) or embed a GIF or screenshots in the post.
Fill in the README with the eval numbers, the section 8 result or an honest note that it hasn’t happened, and ticks in the section 9 checklist for what you actually did.
Remove placeholders. Search the README and post for TBD, [, and _To be filled. Nothing unfinished should be published.

Writing the post
5. Find the official challenge page on DEV and use its submission template as the starting point.
6. Add the tags the README lists: #devchallenge and #hf26challenge. Confirm them against the template.
7. Follow the outline in the README: the problem, what you built, why open weights matter, how it works, results with limitations, the user’s reaction, and what’s next.
8. Include the repo link and the demo.
9. Claim only Best Use of Gemma, unless you really did the others (a hosted demo, a .tech domain, fine-tuning).

Submission
10. Publish the post (not just a draft) and open its public URL in a private window.
11. Use the challenge’s submission mechanism (the template or form on the challenge page) and keep a screenshot or the confirmation.
12. Don’t leave it to the last day. Aim to submit by October 16 so there’s a buffer for time zones and a broken form. Check whether the deadline time is in your timezone or the organiser’s.