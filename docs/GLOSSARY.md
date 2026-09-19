# Glossary

Every technical word used in this project, in plain English, with what it means *here*.

Written for someone who has not met these words before. There is no shame in that — most of
them are ordinary ideas with an intimidating name.

---

## Code and saving work

**Repository (repo)**
A folder of code that git is watching. Your project is one repo.

**Git**
A save history for code. Every save point is kept forever, so you can go back to any of
them. Runs on your computer, needs no internet.

**Commit**
One save point. Holds every file exactly as it was, plus the time, who made it, and a
message saying what changed and why.

**GitHub**
A website that keeps a copy of your git history online. This is how you hand work to your
professor and share it with your team. Git and GitHub are not the same thing.

**Push / pull**
Push = send my commits to GitHub. Pull = get other people's commits down.

**Branch**
A separate line of work. You can try something on a branch without touching the main code.

**Pull request (PR)**
"Please look at my branch and merge it." This is where a teammate reviews your work before
it joins the main code.

**Merge**
Joining a branch back into the main code.

---

## Data

**DVC (Data Version Control)**
Git, but for big data files. Git is bad at large files, so DVC stores the data in the cloud
and puts one small note in git saying *this commit uses the data with this exact
fingerprint*.

*In your project:* 16 MB of readings, 39 files, tracked as one fingerprint.

**Fingerprint / hash / md5**
A short code calculated from a file's contents. Change one number and the code changes
completely. It answers one question exactly: is this the same data or not?

**Versioning**
Being able to say *which exact version* of something you used. Code versioning = git. Data
versioning = DVC.

**Bucket / object storage**
A folder in the cloud. Google's version is called Cloud Storage. Addresses start with
`gs://`.

**Schema**
The shape of your data: which columns exist and what type each one is.

**Data contract**
A set of rules your data must always satisfy. Not suggestions — if a rule breaks, the
pipeline stops.

*In your project:* `src/contract.py`. No negative readings, no duplicate station-hours,
timestamps on the hour, units the same everywhere.

---

## Talking to other systems

**API (Application Programming Interface)**
A way for one program to ask another program for something. OpenAQ has an API: you send a
request, it sends back air quality data.

**Endpoint** *(two meanings — be careful)*
1. **API endpoint**: one specific address you can ask for data.
2. **Model endpoint**: a server running your model that answers prediction requests. This
   is the expensive kind that bills by the hour.

**API key**
A password for an API. Proves it is you asking.

*In your project:* stored in `.env`, never in git. A committed key is an automatic
deduction.

**HTTP 200 / 401 / 429 / 500**
Status codes an API returns.
- 200 = fine
- 401 = your key is wrong
- 429 = you asked too fast, slow down
- 500 = their server broke

**Rate limit**
How many requests you may send per minute. OpenAQ allows 60.

**Timeout**
Giving up waiting for a reply.

---

## Machine learning

**Model**
A learned recipe. Give it numbers, it gives you a prediction.

**Training**
Showing the model past examples so it learns the pattern.

**Feature**
One number the model uses to decide.

*In your project:* PM2.5 one hour ago, three hours ago, the hour of the day.

**Lag feature**
A feature that is simply "the value N hours ago". The main signal in a forecast.

**Label / target**
The answer you are trying to predict. Here: PM2.5 in six hours.

**Inference / scoring / prediction**
Using a trained model to get an answer. Three words for the same thing.

**Baseline**
The dumbest reasonable method, measured first so you know whether your model is actually
better.

*In your project:* persistence — "the value in six hours is the value now". Mean error
16.25 µg/m³ at +6h.

**MAE (mean absolute error)**
On average, how far off the prediction was. Lower is better. In the same units as the thing
you predict (here, µg/m³).

**Leakage**
When the model accidentally sees information it will not have in real life. It scores
brilliantly in testing and fails in production.

*In your project:* building lag features across stations instead of within each one would
let station A's history leak into station B.

**Train/validation/test split**
Splitting data into three parts: learn from one, tune on the second, judge on the third
once.

**Time-ordered split**
For time data, train on earlier, test on later. Never random — random lets the model see
the future.

**Overfitting**
The model memorises the training data instead of learning the pattern. Great on data it has
seen, bad on anything new.

**Seed**
A number that makes random things repeatable. Same seed = same result.

**Seed variance / noise**
How much your score moves just from changing the seed, with nothing else changed. If your
"improvement" is smaller than this, it is not an improvement.

---

## Packaging and shipping

**Container**
A box holding your code plus everything it needs to run — the right Python, the right
libraries. It runs the same on your laptop and in the cloud.

**Docker**
The most common tool for building and running containers.

**Image**
The saved container, ready to run. Like a file. A running copy is a container.

**Registry**
A website that stores images. Google's is Artifact Registry.

**Tag**
A label on an image, like `v1` or `9ff28c9`. A person can move a tag.

**Digest**
A fingerprint of the image's actual contents (`sha256:0418bed...`). Cannot be moved. Always
trust the digest over the tag.

*Why this matters:* in Lab 5 the same tag was pushed three times in one afternoon. The tag
ended up naming a commit whose code was not in the image. The digest was still right.

**Deploy**
Put the thing somewhere it can actually be used.

**Staging / production**
Staging = the test area. Production = where real users are.

---

## Running it automatically

**CI (Continuous Integration)**
Every time you save code to GitHub, a robot automatically runs your tests. If they fail, it
tells you and blocks the change.

*Why:* it catches broken code before a human wastes time on it.

**CD (Continuous Deployment/Delivery)**
The same robot, going further: if tests pass, it builds and ships the new version
automatically.

**CI/CD**
The two together. Usually said as one word.

*In your project:* on every commit — check style, run the contract tests, run the breakage
tests, build the image, run an integration test.

**Pipeline** *(two meanings)*
1. The steps your data goes through: download → clean → features → train.
2. The CI robot's list of steps.

Context tells you which.

**Batch**
Do a lot of work at once, on a schedule. "Every hour, score all 39 stations."

**Online / real-time**
Answer one request at a time, immediately, whenever someone asks.

*Your project is batch.* An always-on endpoint costs ~6,400 THB/month whether anyone uses
it or not. Your hourly batch costs ~46.

**Scheduler / cron**
A clock that starts your job automatically. Google's is Cloud Scheduler.

**Job**
One run of a task that starts, does work, and stops.

**Orchestration**
Running several steps in the right order, where step 2 waits for step 1.

---

## Speed and size

**Latency**
How long one request takes.

**p50 / p95 / p99 (percentiles)**
Sort every request by time. p50 = the middle one. p95 = slower than 95% of requests. p99 =
the slow tail.

*Why not the average:* the average hides the slow ones, and the slow ones are what users
complain about.

**Throughput / RPS**
How many requests per second the system handles.

**Concurrency**
How many requests are happening at the same time.

**SLO (Service Level Objective)**
A promise you make about your own system, with a number.

*Example:* "p95 under 100 ms at concurrency 10."

**Error budget**
How much failure the SLO allows. 99.9% uptime = about 43 minutes down per month. That is
your budget to spend.

---

## Watching it

**Monitoring**
Collecting numbers about the running system so you know it is alive and behaving.

**Metric**
One number you record over time. Rows processed, stations excluded, run duration.

**Dashboard**
A page of charts showing those metrics.

**Alert**
An automatic message when a metric crosses a line you set. Email, Slack, whatever.

**Threshold**
The line that triggers the alert.

**Log**
A text record of what the program did, line by line. What you read when something breaks.

**Drift**
The data slowly becoming different from what the model was trained on. The model gets worse
without anyone changing anything.

*In your project:* burning season. March median 76, June median 5.6.

**PSI (Population Stability Index)**
A number measuring how much a distribution moved. Bigger = moved more.

*Careful:* PSI measures how far the data moved, **not** how much the model minds. Those are
different questions.

**Staleness**
Data being old. Not missing — old. Still there, still looks fine, but no longer true.

*This is the failure your whole project is built around.*

---

## Testing

**Test**
Code that checks other code. Runs automatically.

**Unit test**
Tests one small function on its own. No network, no data files.

**Data contract test**
Checks the incoming data still matches its promised shape.

**Model behaviour test**
Checks the model does not do something the domain forbids. "Risk must not fall as pollution
rises."

**Integration test**
Checks the whole thing works together, usually inside the real container.

**Fixture**
Prepared test data that a test starts from.

**Mutation testing**
Deliberately breaking your own code to check a test notices. If no test goes red, that test
was not really testing anything.

*In your project:* I disabled the negative-value rule; exactly two tests went red; restored
it and they went green. That is how you know the tests work.

**Regression**
Something that used to work and now does not.

---

## Cloud and permissions

**Cloud provider**
Google Cloud, AWS, Azure. You are on Google Cloud.

**Project (GCP)**
Your account's container for everything. Yours is `itcs355-6688010`.

**Region**
Which data centre. Yours is `asia-southeast1` (Singapore).

**Instance / machine type**
The size of rented computer. `e2-standard-4` = 4 processors, 16 GB memory.

**Spot / preemptible**
Cheap rented computers that Google can take back with little warning. About 45% cheaper.
Only usable if your job can resume.

**Credentials**
Anything that proves who you are: passwords, API keys, key files.

**IAM (Identity and Access Management)**
The system deciding who may do what.

**Service account**
A login for a program, not a person.

**Role**
A bundle of permissions given to an identity. `storage.objectViewer` = may read files, may
not write them.

**Least privilege**
Give each identity only what its job needs.

*Measured in Lab 5:* asking for a narrower *scope* changed nothing — the write still
succeeded. Binding a narrower *role* refused it. A scope is what the code asks for; a role
is what someone else decided it may have. Only the second is a wall.

**Teardown**
Deleting everything you created, so it stops costing money. Leaving resources running after
submission is an automatic deduction.

---

## Words about doing the work

**Reproducible**
Someone else can run it and get exactly the same answer. This is what R1's 6 marks are for.

**Lineage**
The record of where a model came from: which code, which data, which settings, which job.

**Artifact**
Any file your pipeline produces: a model file, a report, a forecast.

**Model card**
A one-page document about the model: what it does, what data, its limits, when not to trust
it.

**Gate**
A check that can stop the process. An evaluation gate refuses to register a weak model. A
staleness gate refuses to forecast from old data.

**Post-mortem**
A short write-up after something broke: what happened, why, what changed so it does not
happen again. Blames the system, not a person.

**Rollback**
Going back to the previous working version after a bad release.

**Canary**
Sending a small share of real traffic to a new version to see if it is worse, before giving
it everything.

**Blue/green**
Two full copies of the system. Switch traffic from one to the other, switch back if it goes
wrong.
