
2C:/Users/90552/desktop/sinav-frontend/src/index.js¡"const express = require('express');
const cors = require('cors');
const examRoutes = require('./routes/exam');

const app = express();
app.use(cors());
app.use(express.json());
app.use('/api/exam', examRoutes);

const PORT = 5000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));

// ==== backend/routes/exam.js ====
const router = express.Router();

let exams = [];
let responses = [];

router.post('/start', (req, res) => {
    const { duration, questions } = req.body;
    const id = Date.now();
    exams.push({ id, duration, questions });
    res.json({ id });
});

router.post('/submit-answers', (req, res) => {
    const { examId, name, answers } = req.body;
    const exam = exams.find(e => e.id === examId);
    if (!exam) return res.status(404).json({ error: 'Exam not found' });

    const wrongAnswers = exam.questions.map((q, idx) => (
        answers[idx] !== q.answer ? idx : null
    )).filter(i => i !== null);

    responses.push({ examId, name, wrongAnswers });
    res.json({ wrongAnswers });
});

router.get('/results/:examId', (req, res) => {
    const { examId } = req.params;
    const result = responses.filter(r => r.examId == examId);
    res.json(result);
});

module.exports = router;

// ==== frontend/src/pages/StartExam.js ====
import React, { useState } from 'react';
import axios from 'axios';

export default function StartExam() {
    const [duration, setDuration] = useState(30);
    const [questions, setQuestions] = useState([{ q: '', answer: '' }]);

    const startExam = async () => {
        const response = await axios.post('http://localhost:5000/api/exam/start', {
            duration,
            questions
        });
        alert(`Exam ID: ${response.data.id}`);
    };

    return (
        <div>
            <h2>Start Exam</h2>
            <label>Duration (minutes):</label>
            <input type="number" value={duration} onChange={e => setDuration(Number(e.target.value))} />
            <h3>Questions</h3>
            {questions.map((q, idx) => (
                <div key={idx}>
                    <input
                        placeholder="Question"
                        value={q.q}
                        onChange={e => {
                            const updated = [...questions];
                            updated[idx].q = e.target.value;
                            setQuestions(updated);
                        }}
                    />
                    <input
                        placeholder="Correct Answer"
                        value={q.answer}
                        onChange={e => {
                            const updated = [...questions];
                            updated[idx].answer = e.target.value;
                            setQuestions(updated);
                        }}
                    />
                </div>
            ))}
            <button onClick={() => setQuestions([...questions, { q: '', answer: '' }])}>Add Question</button>
            <button onClick={startExam}>Start</button>
        </div>
    );
}

// ==== frontend/src/pages/SubmitAnswers.js ====
import React, { useState } from 'react';
import axios from 'axios';

export default function SubmitAnswers() {
    const [examId, setExamId] = useState('');
    const [name, setName] = useState('');
    const [answers, setAnswers] = useState([]);
    const [wrong, setWrong] = useState([]);

    const submit = async () => {
        const response = await axios.post('http://localhost:5000/api/exam/submit-answers', {
            examId: Number(examId),
            name,
            answers
        });
        setWrong(response.data.wrongAnswers);
    };

    return (
        <div>
            <h2>Submit Answers</h2>
            <input placeholder="Exam ID" value={examId} onChange={e => setExamId(e.target.value)} />
            <input placeholder="Your Name" value={name} onChange={e => setName(e.target.value)} />
            <textarea placeholder="Answers (comma separated)" onChange={e => setAnswers(e.target.value.split(','))} />
            <button onClick={submit}>Submit</button>
            {wrong.length > 0 && (
                <div>
                    <h3>Wrong Questions:</h3>
                    <ul>
                        {wrong.map(i => <li key={i}>Question #{i + 1}</li>)}
                    </ul>
                </div>
            )}
        </div>
    );
}
¡" 2:file:///C:/Users/90552/desktop/sinav-frontend/src/index.js