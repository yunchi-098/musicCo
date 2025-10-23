; (function () {
	const vscode = acquireVsCodeApi();
	const deepseekSvg = `<?xml version="1.0" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 20010904//EN"
 "http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd">
<svg version="1.0" xmlns="http://www.w3.org/2000/svg"
 width="12pt" height="12pt" viewBox="0 0 1024.000000 1024.000000"
 preserveAspectRatio="xMidYMid meet">

<g transform="translate(0.000000,1024.000000) scale(0.100000,-0.100000)"
fill="#FFFFFF" stroke="none">
<path d="M7094 8946 c-37 -17 -59 -45 -112 -151 -219 -438 -209 -1052 25
-1520 120 -238 291 -436 533 -616 103 -76 130 -108 130 -149 0 -30 -125 -416
-144 -445 -13 -20 -24 -25 -60 -25 -35 0 -74 15 -188 73 -311 158 -422 248
-948 777 -516 518 -658 642 -981 858 -118 78 -173 139 -223 242 -28 58 -31 75
-31 155 0 80 3 97 31 155 57 121 153 217 282 285 63 34 77 62 45 97 -93 103
-452 116 -811 28 -154 -38 -270 -75 -542 -175 -325 -120 -322 -119 -472 -95
-459 73 -1008 63 -1408 -26 -246 -55 -408 -112 -626 -219 -394 -194 -737 -493
-1011 -881 -514 -728 -685 -1580 -512 -2564 139 -796 517 -1515 1104 -2103
616 -617 1348 -1016 2125 -1156 388 -70 834 -79 1310 -25 644 73 1149 278
1652 673 l118 92 37 -20 c240 -122 838 -190 1208 -137 263 38 360 70 427 144
45 50 61 99 56 172 -6 87 -22 104 -166 172 -192 91 -454 201 -600 251 -114 39
-203 86 -202 106 0 3 73 87 161 186 209 234 337 390 453 548 362 499 609 1100
761 1858 65 325 77 426 74 619 -2 96 0 185 5 198 11 32 31 40 148 57 215 32
388 88 577 185 159 83 286 176 411 300 265 265 415 590 486 1052 25 163 24
263 -4 320 -37 75 -121 115 -178 85 -16 -9 -86 -72 -156 -141 -147 -143 -234
-205 -350 -248 -80 -29 -92 -31 -303 -38 -185 -7 -235 -12 -316 -33 -189 -49
-357 -140 -492 -266 -37 -35 -69 -62 -70 -60 -2 2 -13 42 -26 89 -53 204 -157
352 -335 472 -32 22 -127 73 -212 114 -183 87 -251 131 -327 213 -67 73 -101
142 -156 317 -44 141 -66 179 -117 200 -40 17 -41 17 -80 0z m-5466 -2711
c867 -149 1609 -539 2247 -1179 272 -273 420 -463 836 -1077 345 -510 537
-764 775 -1023 187 -204 486 -468 684 -603 38 -27 69 -51 70 -55 1 -25 -547
-21 -685 5 -195 37 -367 96 -484 167 -43 25 -163 112 -267 192 -532 409 -908
659 -1141 758 -237 100 -346 69 -346 -98 1 -116 50 -263 134 -398 113 -183
119 -251 27 -324 -141 -111 -387 -112 -698 -5 -120 42 -186 78 -390 216 -618
419 -1040 930 -1353 1639 -164 372 -271 749 -326 1140 -26 187 -43 423 -35
478 8 56 40 102 89 129 134 73 551 92 863 38z m4144 -289 c163 -41 262 -101
440 -267 131 -121 239 -252 370 -449 140 -210 220 -370 226 -452 4 -58 4 -59
-39 -101 -79 -78 -279 -135 -408 -117 -122 17 -193 51 -307 144 -92 76 -125
115 -162 194 -25 53 -27 67 -27 187 0 72 4 164 9 206 12 101 -7 158 -72 224
-70 71 -147 104 -271 114 -125 11 -187 38 -214 92 -23 49 -14 89 35 144 46 52
75 69 150 89 79 22 164 19 270 -8z m-175 -549 c28 -31 33 -44 33 -84 0 -66
-27 -106 -84 -128 -60 -23 -114 -9 -149 38 -48 63 -40 135 20 187 33 30 41 32
91 28 48 -4 60 -10 89 -41z"/>
</g>
</svg>
`;
	const userSvg = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 mr-2 avatar"><path stroke-linecap="round" stroke-linejoin="round" d="M17.982 18.725A7.488 7.488 0 0012 15.75a7.488 7.488 0 00-5.982 2.975m11.963 0a9 9 0 10-11.963 0m11.963 0A8.966 8.966 0 0112 21a8.966 8.966 0 01-5.982-2.275M15 9.75a3 3 0 11-6 0 3 3 0 016 0z" /></svg>`;
	const clipboardSvg = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" /></svg>`;
	const plusSvg = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>`;
	const insertSvg = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M11.25 4.5l7.5 7.5-7.5 7.5m-6-15l7.5 7.5-7.5 7.5" /></svg>`;
	const copedSvg = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>`;
	const arrowSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" class="h-4 w-4 m-1 md:m-0" stroke-width="2"><path d="M.5 1.163A1 1 0 0 1 1.97.28l12.868 6.837a1 1 0 0 1 0 1.766L1.969 15.72A1 1 0 0 1 .5 14.836V10.33a1 1 0 0 1 .816-.983L8.5 8 1.316 6.653A1 1 0 0 1 .5 5.67V1.163Z" fill="currentColor"></path></svg>`;
	const editSvg = `<svg stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4" height="1em" width="1em" xmlns="http://www.w3.org/2000/svg"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`;
	const clearSvg = `<svg t="1676466716218" class="h-4 w-4 icon"  viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="2778" width="200" height="200"><path d="M752.3 91.3l-34.7-16.8c-26.1-12.6-57.5-1.7-70.1 24.5L531.8 338.4l-6.9-3.4c-64.1-30.9-141.1-4.1-172 60l-10 20.7 375.2 181.2 10-20.7c30.9-64.1 4.1-141.1-60-172l-6.9-3.3 115.6-239.4c12.6-26.2 1.7-57.6-24.5-70.2zM702 630L326.3 448.6c-22.9 30-52.5 63.8-90.1 97.4-57.5 51.4-114.5 85.3-159.6 107.4 13.1 41.4 40.8 61.3 60.3 82.3 7.2 7.8 118.3-112.3 126.3-104.6 8 7.7-87 143.1-78.3 150.6 25.9 22.2 55 43.4 86.7 63.3 6.5 4.1 145.1-185 151.3-181.6 12.4 6.8-87.9 217.4-74.8 223.7 13 6.3 26.1 12.2 39.1 17.7 45.1 19 89.9 33 132.8 42.2 13.1 2.8 82-234.4 94.6-232.5 12.7 1.9-30.8 242.9-18.7 243.9 36.5 3 70.6 1.9 100.9-3.3-10.5-54.4-18.2-124.6-12.5-205.8 3.2-44.5 9.9-84.5 17.7-119.3z" p-id="2779" fill="#bfbfbf"></path></svg>`;
	const regenerateSvg = `<svg stroke="currentColor" fill="none" stroke-width="1.5" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round" class="h-3 w-3 flex-shrink-0" height="1em" width="1em" xmlns="http://www.w3.org/2000/svg"><polyline points="1 4 1 10 7 10"></polyline><polyline points="23 20 23 14 17 14"></polyline><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"></path></svg>`;
	const markdownSvg = `<svg class="w-6 h-6" t="1687004795634" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="6710" width="200" height="200"><path d="M85.333333 682.666667 85.333333 341.333333 170.666667 341.333333 298.666667 469.333333 426.666667 341.333333 512 341.333333 512 682.666667 426.666667 682.666667 426.666667 462.08 298.666667 590.08 170.666667 462.08 170.666667 682.666667 85.333333 682.666667M682.666667 341.333333 810.666667 341.333333 810.666667 512 917.333333 512 746.666667 704 576 512 682.666667 512 682.666667 341.333333Z" p-id="6711"></path></svg>`;
	let stopSrollToBottom = false;
	function throttle(func, delay) {
		let lastCall = 0;
		return function () {
			const now = Date.now();
			if (now - lastCall < delay) {
				return;
			}
			lastCall = now;
			return func.apply(this, arguments);
		}
	}
	function utf8_to_b64(str) {
		return btoa(new TextEncoder().encode(str).reduce((data, byte) => data + String.fromCharCode(byte), ''));
	}

	function b64_to_utf8(str) {
		return new TextDecoder().decode(Uint8Array.from(atob(str), c => c.charCodeAt(0)));
	}
	function getAskBtnWrapper(message) {
		let encodedMessage = utf8_to_b64(JSON.stringify(message));
		return `
			<div class="flex justify-between items-center">
			    <button class="clear-btn p-1.5 flex items-center rounded-lg" title="clear question">
				  ${clearSvg}
				</button>
				<button class="regenerate-btn p-1.5 flex items-center rounded-lg" title="regenerate response">
				  ${regenerateSvg}
				</button>
				<button class="edit-btn p-1.5 flex items-center rounded-lg" title="edit and ask again">
				  ${editSvg}
				</button>
				<input type="hidden" value="${encodedMessage}"/>
			</div>
		`;
	}
	function getAnswerBtnWrapper() {
		return `
			<div class="flex justify-between items-center">
				<button class="copy-answer-btn p-1.5 flex items-center rounded-lg" title="copy to clipboard">
				  ${clipboardSvg}
				</button>
				<button class="insert-answer-btn p-1.5 flex items-center rounded-lg" title="insert at cursor">
				  ${insertSvg}
				</button>
				<button class="opennew-answer-btn p-1.5 flex items-center rounded-lg" title="insert into new file">
				  ${plusSvg}
				</button>
				<button class="export-markdown-btn p-1.5 flex items-center rounded-lg" title="export markdown">
				  ${markdownSvg}
				</button>
			</div>
		`;
	}
	function getCodeBtnWrapper() {
		return `
			<div class="flex justify-between items-center">
				<button class="copy-code-btn p-1.5 flex items-center rounded-lg" title="copy to clipboard">
				  ${clipboardSvg}
				</button>
				<button class="insert-code-btn p-1.5 flex items-center rounded-lg" title="insert at cursor">
				  ${insertSvg}
				</button>
				<button class="opennew-code-btn p-1.5 flex items-center rounded-lg" title="insert into new file">
				  ${plusSvg}
				</button>
			</div>
		`;
	}
	function highlightBlock(str, lang) {
		let block = `<pre class="code-block-wrapper"><div class="code-block-header flex justify-between items-center"><span>${lang}</span>${getCodeBtnWrapper()}</div><code class="hljs language-${lang}`;
		if (str.length > 1800) {
			block += ` code-block-body">${str}</code><div class="code-block-footer flex justify-end items-center">${getCodeBtnWrapper()}</div>`;
		} else {
			block += ` code-block-body code-block-body-end">${str}</code>`;
		}
		block += `</pre>`;
		return block;
	}
	var markdown = window.markdownit({
		linkify: true,
		highlight(code, language = 'javascript') {
			const validLang = !!(language && hljs.getLanguage(language))
			if (validLang) {
				return highlightBlock(hljs.highlight(language, code, true).value, language)
			}
			return highlightBlock(hljs.highlightAuto(code).value, '')
		}
	});
	const qaList = document.getElementById('qa-list');
	const askButton = document.getElementById('ask-button');
	const questionInput = document.getElementById('question-input');
	const stopGenerating = document.getElementById('stop-generating');
	const selectLanguage = document.getElementById('select-language');
	const selectTemperature = document.getElementById('select-temperature');
	const toggleSidebar = document.getElementById('toggle-side-bar');
	const sidebar = document.getElementById('sidebar');
	const conversations = document.getElementById('conversations');
	let prompts = document.getElementById('prompts');
	const scrollToBottom = throttle(() => {
		if (stopSrollToBottom) return;
		requestAnimationFrame(() => {
			qaList.scrollTop = qaList.scrollHeight;
		})
	}, 500);
	qaList.addEventListener("scroll", throttle(() => {
		const nearBottom = qaList.scrollHeight - qaList.scrollTop - qaList.clientHeight <= 50;
		stopSrollToBottom = !nearBottom;
	}, 500));
	let totalMsg = '';
	window.addEventListener('message', (event) => {
		const message = event.data;
		// 获取prompt和代码
		const { type, value, code, status, content, languageId = 'javascript' } = message;
		//判断消息的类型
		switch (type) {
			//如果是增加提问
			case 'addQuestion':
				let valueHtml = '';
				if (value) {
					//把value转化为源代码的形式
					valueHtml = `${markdown.render(value)}`;
				}
				let codeHtml = '';
				if (code) {
					//把code转化为源代码的形式
					codeHtml = `${markdown.render(`\`\`\`${languageId}\r\n${code}\r\n\`\`\``)}`;
				}
				qaList.innerHTML += `
				<div class="question-container bg-gray-600 text-white rounded my-1 p-3">
				  <div class="flex justify-between items-center">
				    <div class="flex items-center font-bold">${userSvg}<span class="ml-1">You</span></div>
					${getAskBtnWrapper(message)}
				  </div>
				  <p>${valueHtml}</p>
				  ${codeHtml}
			    </div>
			`;
				scrollToBottom();
				startLoading();
				break;
			case 'addResponse':
				let answerHTml = '';
				if (status === 'start') {
					totalMsg = value;
					answerHTml = markdown.render(totalMsg);
					qaList.innerHTML += `
					<div class="answer-container p-3 rounded-t">
					  <div class="flex justify-between items-center">
						<div class="flex items-center">${deepseekSvg}<span class="ml-1">deepseek</span></div>
						${getAnswerBtnWrapper()}
					  </div>
					  <input  type="hidden" value="${totalMsg}"/>
					  <div class="mt-1 responseContent  pb-3">${answerHTml}</div>
				    </div>
				`;
					scrollToBottom()
				} else if (status === 'continue') {
					const responseContents = document.querySelectorAll('.responseContent');
					const responseContent = responseContents[responseContents.length - 1];
					if (responseContent) {
						totalMsg += value;
						answerHTml = markdown.render(totalMsg)
						responseContent.innerHTML = answerHTml;
						responseContent.previousElementSibling.value = totalMsg;
						scrollToBottom()
					}
				} else {
					scrollToBottom()
					stopLoading();
					stopSrollToBottom = false;
				}
				break;
			case 'requestError':
				stopLoading();
				break;
			case 'clearList':
				qaList.innerHTML = '';
				break;
			case 'refreshConversations':
				conversations.innerHTML = content;
				break;
			case 'focusInput':
				questionInput.focus();
				break;
			case 'showConversation':
				renderConversation(content);
				break;
			case 'refreshPrompts':
				prompts.innerHTML = content;
				if (!message.silent) {
					if (prompts.children && prompts.children.length > 0) {
						prompts.classList.remove('hidden');
						focusSelectedPrompt();
					}
				}
				break;
			default:
				break;
		}
	});
	function focusSelectedPrompt() {
		if (prompts && prompts.children.length > 0) {
			let promptItems = Array.from(prompts.children);
			promptItems[selectedIndex]?.focus();
			promptItems[selectedIndex]?.children[1]?.classList.remove('hidden');
		}
	}
	/**
	 * 通过用户在输入框中的内容进行提问
	 */
	function askQuestionByInputValue() {
		// 检查输入框的值是否存在且长度大于零。input.value 表示输入框的当前值
		if (questionInput.value?.length > 0) {
			lastValue = questionInput.value;
			//使用 vscode.postMessage 方法将消息发送给 VS Code 编辑器
			vscode.postMessage({
				type: 'askdeepseek',//消息的类型为 'askdeepseek'
				value: questionInput.value,//表示输入框的值，作为用户的提问内容。
			});
			askButton.disabled = true;
			askButton.style.backgroundColor = 'rgba(0, 0, 0, 0)';
			questionInput.value = '';//将输入框的值设置为空字符串，以清除输入框中的文本内容
		}
	}
	/**
	 * 处理按下事件
	 * @param {*} event 事件对象
	 * @returns 
	 */
	function handleKeydown(event) {
		//用于检查按下的键是否是回车键（Enter）且没有按下 Shift 键。
		//如果同时满足这两个条件，即按下的键是回车键且没有按下 Shift 键，将执行条件语句中的代码块。
		if (!event.shiftKey && event.keyCode === 13) {
			//它用于从输入框中获取问题的值并将其发送给 VS Code 编辑器。
			askQuestionByInputValue();
			//阻止事件的默认行为发生
			//阻止默认行为是为了阻止按下回车键后，防止触发表单提交或换行等默认行为。
			event.preventDefault();
			//返回 false 也是为了阻止事件的默认行为，与 event.preventDefault() 的作用相同。
			return false;
		} else if (event.target.value === '' && event.key === '/') {
			if (prompts.children && prompts.children.length > 0) {
				prompts.classList.remove('hidden');
				prompts.children[selectedIndex]?.focus();
				prompts.children[selectedIndex]?.children[1]?.classList.remove('hidden');
			}
		}
	}
	function copyCode(targetButton) {
		let codeElement = targetButton?.parentElement?.parentElement?.parentElement?.lastElementChild;
		if (codeElement?.tagName !== 'CODE') {
			codeElement = codeElement.previousElementSibling;
		}
		let value = codeElement?.textContent;
		if (!value) return;
		navigator.clipboard
			.writeText(value)
			.then(() => {
				targetButton.innerHTML = copedSvg;
				setTimeout(() => {
					targetButton.innerHTML = clipboardSvg;
				}, 1500);
			});
	}
	function insertCodeToCursor(targetButton) {
		let codeElement = targetButton?.parentElement?.parentElement?.parentElement?.lastElementChild;
		if (codeElement?.tagName !== 'CODE') {
			codeElement = codeElement.previousElementSibling;
		}
		let value = codeElement?.textContent;
		if (!value) return;
		vscode.postMessage({
			type: 'insertToCursor',
			value
		});
	}
	function insertCodeToNewTab(targetButton) {
		let codeElement = targetButton?.parentElement?.parentElement?.parentElement?.lastElementChild;
		if (codeElement?.tagName !== 'CODE') {
			codeElement = codeElement.previousElementSibling;
		}
		let value = codeElement?.textContent;
		if (!value) return;
		vscode.postMessage({
			type: 'insertToNewTab',
			value
		});
	}
	function copyAnswer(targetButton) {
		const value = targetButton?.parentElement?.parentElement?.nextElementSibling.value;
		if (!value) return;
		navigator.clipboard
			.writeText(value)
			.then(() => {
				//表示复制操作成功
				targetButton.innerHTML = copedSvg;
				//在 1500 毫秒（1.5 秒）后将 targetButton 的 HTML 内容更改回 clipboardSvg
				setTimeout(() => {
					targetButton.innerHTML = clipboardSvg;
				}, 1500);
			});
	}
	function insertAnswerToCursor(targetButton) {
		const value = targetButton?.parentElement?.parentElement?.nextElementSibling?.value;
		if (!value) return;
		vscode.postMessage({
			type: 'insertToCursor',
			value
		});
	}
	function insertAnswerToNewTab(targetButton) {
		const value = targetButton?.parentElement?.parentElement?.nextElementSibling?.value;
		if (!value) return;
		vscode.postMessage({
			type: 'insertToNewTab',
			value
		});
	}
	function onQuestionInputChange() {
		if (questionInput.value.trim() === '') {
			askButton.disabled = true;
			askButton.style.backgroundColor = 'rgba(0, 0, 0, 0)';
		} else {
			askButton.disabled = false;
			askButton.style.backgroundColor = 'rgb(171, 104, 255)';
		}
	}
	function startLoading() {
		askButton.innerHTML = `<span></span><span></span><span></span>`;
		stopGenerating?.classList?.remove('hidden');
	}
	function stopLoading() {
		askButton.innerHTML = arrowSvg;
		stopGenerating?.classList?.add('hidden');
	}
	function renderConversation(conversation) {
		const { messages } = conversation;
		const messagesHtml = messages.slice(1).map((message) => {
			const { role, content } = message;
			const contentHtml = markdown.render(content)
			let html = '';
			if (role === 'user') {
				html += `
				<div class="question-container bg-gray-600 text-white rounded  my-1 p-3">
				  <div class="flex justify-between items-center">
				  <div class="flex items-center">${userSvg}<span class="ml-1">You</span></div>
				  ${getAskBtnWrapper({ type: 'addQuestion', value: message.content })}
				  </div>
				  <p>${contentHtml}</p>
			    </div>`;
			} else {
				html += `
				<div class="answer-container  rounded-t p-3">
					<div class="flex justify-between items-center">
					<div class="flex items-center">${deepseekSvg}<span class="ml-2">deepseek</span></div>
					${getAnswerBtnWrapper()}
					</div>
					<input  type="hidden" value="${content}"/>
					<div class="mt-2 responseContent pb-3">${contentHtml}</div>
				</div>`;
			}
			return html;
		}
		).join('');
		qaList.innerHTML = messagesHtml;
		scrollToBottom();
	}
	function stopGeneratingResponse() {
		vscode.postMessage({ type: 'stopGenerating' });
		askButton.disabled = true;
		askButton.style.backgroundColor = 'rgba(0, 0, 0, 0)';
		stopLoading();
	}
	function editAndReSend(targetButton) {
		const messageValue = targetButton.parentElement.lastElementChild.value;
		let decodedMessage = JSON.parse(b64_to_utf8(messageValue));
		const { value, code, languageId = 'javascript' } = decodedMessage || {};
		let inputValue = '';
		if (value) {
			inputValue += value;
		}
		if (code) {
			inputValue += `\r\n\`\`\`${languageId}\r\n${code}\r\n\`\`\``;
		}
		questionInput.value = inputValue;
		questionInput.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
		onQuestionInputChange();
	}
	function regenerateReseponse(targetButton) {
		editAndReSend(targetButton);
		askQuestionByInputValue()
	}
	function clearQuestion(targetButton) {
		const questionContainer = targetButton.parentElement.parentElement.parentElement;
		const responseContainer = questionContainer.nextElementSibling;
		questionContainer?.remove();
		responseContainer?.remove();
	}
	function handleLanguage() {
		const value = selectLanguage.value;
		vscode.postMessage({
			type: 'changeLanguage',
			value
		});
	}
	function handleTemperature() {
		const value = selectTemperature.value;
		vscode.postMessage({
			type: 'changeTemperature',
			value
		});
	}
	function startNewChat() {
		vscode.postMessage({
			type: 'startNewChat'
		});
	}
	function exportMarkdown(targetButton) {
		const value = targetButton?.parentElement?.parentElement?.nextElementSibling.value;
		if (!value) return;
		vscode.postMessage({
			type: 'exportMarkdown',
			value
		});
	}
	function deleteConversation(targetButton) {
		vscode.postMessage({
			type: 'deleteConversation',
			value: targetButton.dataset.id
		});
	}
	function showConversation(targetButton) {
		const editConversations = document.querySelectorAll('.edit-conversation');
		const deleteConversations = document.querySelectorAll('.delete-conversation');
		[...editConversations, ...deleteConversations].forEach(item => item.classList.add('hidden'));
		const editConversation = targetButton.parentElement.nextElementSibling;
		const deleteConversation = editConversation.nextElementSibling;
		[editConversation, deleteConversation].forEach(item => item.classList.remove('hidden'));
		vscode.postMessage({
			type: 'showConversation',
			value: targetButton.dataset.id
		});
	}
	function editConversation(targetButton) {
		const conversationContent = targetButton.previousElementSibling;
		const conversationContentButton = conversationContent.firstElementChild;
		const conversationContentInput = conversationContentButton.nextElementSibling;
		conversationContentInput.value = b64_to_utf8(conversationContentInput.value);
		conversationContentButton.classList.add('hidden');
		conversationContentInput.classList.remove('hidden');
		conversationContentInput.focus();
		conversationContentInput.select();
		conversationContentInput.setSelectionRange(0, 0);
		const deleteConversation = targetButton.nextElementSibling;
		const confirmEditConversation = deleteConversation.nextElementSibling;
		const cancelEditConversation = confirmEditConversation.nextElementSibling;
		targetButton.classList.add('hidden');
		deleteConversation.classList.add('hidden');
		confirmEditConversation.classList.remove('hidden');
		cancelEditConversation.classList.remove('hidden');
	}
	function confirmEditonversation(targetButton) {
		const deleteConversation = targetButton.previousElementSibling;
		const editConversation = deleteConversation.previousElementSibling;
		const conversationContent = editConversation.previousElementSibling;
		const conversationContentButton = conversationContent.firstElementChild;
		const conversationContentInput = conversationContentButton.nextElementSibling;
		conversationContentButton.classList.remove('hidden');
		conversationContentInput.classList.add('hidden');
		const cancelEditConversation = targetButton.nextElementSibling;
		targetButton.classList.add('hidden');
		cancelEditConversation.classList.add('hidden');
		const newTitle = conversationContentInput.value;
		if (newTitle) {
			conversationContentButton.innerHTML = newTitle;
			vscode.postMessage({
				type: 'changeConversationTitle',
				id: targetButton.dataset.id,
				title: newTitle
			});
		}
		conversationContentInput.value = utf8_to_b64(conversationContentInput.value)
	}

	function cancelEditonversation(targetButton) {
		const confirmEditConversation = targetButton.previousElementSibling;
		const deleteConversation = confirmEditConversation.previousElementSibling;
		const editConversation = deleteConversation.previousElementSibling;
		const conversationContent = editConversation.previousElementSibling;
		const conversationContentButton = conversationContent.firstElementChild;
		const conversationContentInput = conversationContentButton.nextElementSibling;
		conversationContentButton.classList.remove('hidden');
		conversationContentInput.classList.add('hidden');
		deleteConversation.classList.remove('hidden');
		editConversation.classList.remove('hidden');
		confirmEditConversation.classList.add('hidden');
		targetButton.classList.add('hidden');
		conversationContentInput.value = utf8_to_b64(conversationContentInput.value)
	}
	function deleteAllConversations() {
		vscode.postMessage({
			type: 'deleteAllConversations'
		});
	}
	function toggleSidebarView() {
		sidebar.classList.toggle('hidden');
	}
	function handleConversationsDown(event) {
		if (event.target.classList.contains('edit-conversation-area')) {
			if (!event.shiftKey && event.keyCode === 13) {
				event.preventDefault();
				confirmEditonversation(event.target.parentElement.nextElementSibling.nextElementSibling.nextElementSibling)
				return false;
			}
		}
	}
	let selectedIndex = 0;
	function handleClick(event) {
		//方法用于从当前元素开始向上遍历，查找最近的父级元素中是否存在 'button' 标签
		const targetButton = event.target.closest('button');
		if (targetButton?.classList?.contains('copy-code-btn')) {
			event.preventDefault();
			copyCode(targetButton);
		} else if (targetButton?.classList?.contains('insert-code-btn')) {
			event.preventDefault();
			insertCodeToCursor(targetButton);
		} else if (targetButton?.classList?.contains('opennew-code-btn')) {
			event.preventDefault();
			insertCodeToNewTab(targetButton);
		} else if (targetButton?.classList?.contains('copy-answer-btn')) {
			event.preventDefault();
			copyAnswer(targetButton);
		} else if (targetButton?.classList?.contains('insert-answer-btn')) {
			event.preventDefault();
			insertAnswerToCursor(targetButton);
		} else if (targetButton?.classList?.contains('opennew-answer-btn')) {
			event.preventDefault();
			insertAnswerToNewTab(targetButton);
		} else if (targetButton?.classList?.contains('regenerate-btn')) {
			event.preventDefault();
			regenerateReseponse(targetButton);
		} else if (targetButton?.classList?.contains('edit-btn')) {
			event.preventDefault();
			editAndReSend(targetButton);
		} else if (targetButton?.classList?.contains('new-chat')) {
			event.preventDefault();
			startNewChat();
		} else if (targetButton?.classList?.contains('export-markdown-btn')) {
			event.preventDefault();
			exportMarkdown(targetButton);
		} else if (targetButton?.classList?.contains('delete-conversation')) {
			event.preventDefault();
			deleteConversation(targetButton);
		} else if (targetButton?.classList?.contains('delete-all-conversations')) {
			event.preventDefault();
			deleteAllConversations(targetButton);
		} else if (targetButton?.classList?.contains('conversation-content')) {
			event.preventDefault();
			showConversation(targetButton);
		} else if (targetButton?.classList?.contains('edit-conversation')) {
			event.preventDefault();
			editConversation(targetButton);
		} else if (targetButton?.classList?.contains('confirm-edit-conversation')) {
			event.preventDefault();
			confirmEditonversation(targetButton);
		} else if (targetButton?.classList?.contains('cancel-edit-conversation')) {
			event.preventDefault();
			cancelEditonversation(targetButton);
		} else if (targetButton?.classList?.contains('delete-prompt')) {
			event.preventDefault();
			deletePrompt(targetButton);
		} else if (targetButton?.classList?.contains('clear-btn')) {
			event.preventDefault();
			clearQuestion(targetButton);
		}
		if (event.target.classList.contains('prompt')) {
			prompts.classList.add('hidden');
			selectedIndex = Number(event.target.dataset.index);
			let inputContent = event.target.dataset?.content?.trim();
			if (!inputContent) {
				inputContent = event.target.dataset?.title?.trim();
			}
			if (!inputContent) {
				inputContent = event.target.textContent;
			}
			if (inputContent) {
				questionInput.value = inputContent + '\r\n';
				questionInput.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
				questionInput.focus();
			}
		} else {
			if (!prompts.classList.contains('hidden')) {
				prompts.classList.add('hidden');
			}
		}
	}
	function deletePrompt(targetButton) {
		vscode.postMessage({
			type: 'deletePrompt',
			index: targetButton.dataset.index
		});
	}
	function handleArrowKey(event) {
		if (prompts.classList.contains('hidden')) return;
		let promptItems = Array.from(prompts.children);
		let total = promptItems.length;
		event.preventDefault();
		let oldSelectedItem;
		switch (event.key) {
			case 'ArrowDown':
				oldSelectedItem = promptItems[selectedIndex];
				selectedIndex++;
				if (selectedIndex >= total) {
					selectedIndex = 0;
				}
				oldSelectedItem?.children[1]?.classList.add('hidden');
				focusSelectedPrompt();
				break;
			case 'ArrowUp':
				oldSelectedItem = promptItems[selectedIndex];
				selectedIndex--;
				if (selectedIndex < 0) {
					selectedIndex = total - 1;
				}
				oldSelectedItem?.children[1]?.classList.add('hidden');
				focusSelectedPrompt();
				break;
			case 'Enter':
				prompts.classList.add('hidden');
				let textContent = prompts?.children[selectedIndex]?.firstElementChild?.dataset?.content?.trim();
				if (textContent) {
					questionInput.value = textContent + '\r\n';
					questionInput.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
					questionInput.focus();
				}
				break;
			case 'Escape':
				prompts.classList.add('hidden');
				questionInput.focus();
				break;
			default:
				break;
		}
	}
	askButton.addEventListener('click', askQuestionByInputValue);
	questionInput.addEventListener('input', onQuestionInputChange);
	questionInput?.addEventListener('keydown', handleKeydown);
	stopGenerating?.addEventListener('click', stopGeneratingResponse);
	selectLanguage?.addEventListener('change', handleLanguage);
	selectTemperature?.addEventListener('change', handleTemperature);
	toggleSidebar?.addEventListener('click', toggleSidebarView);
	conversations?.addEventListener('keydown', handleConversationsDown);
	document.addEventListener('click', handleClick);
	document.addEventListener('keydown', handleArrowKey);
	window.addEventListener('DOMContentLoaded', () => {
		questionInput.focus();
	});
})();
