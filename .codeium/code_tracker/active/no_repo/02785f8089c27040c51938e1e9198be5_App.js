
0C:/Users/90552/desktop/sinav-frontend/src/App.js²
// ==== frontend/src/pages/ViewMistakes.js ====
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useParams } from 'react-router-dom';

export default function ViewMistakes() {
  const { examId } = useParams();
  const [data, setData] = useState([]);

  useEffect(() => {
    axios.get(`http://localhost:5000/api/exam/results/${examId}`).then(res => {
      setData(res.data);
    });
  }, [examId]);

  return (
      <div>
        <h2>Exam #{examId} Results</h2>
        {data.map((entry, i) => (
            <div key={i}>
              <h3>{entry.name}</h3>
              <ul>
                {entry.wrongAnswers.map(q => (
                    <li key={q}>Wrong Question #{q + 1}</li>
                ))}
              </ul>
            </div>
        ))}
      </div>
  );
}
² 28file:///C:/Users/90552/desktop/sinav-frontend/src/App.js