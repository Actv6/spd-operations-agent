/** Presentation only: recognize explicit labels; never infer facts or rewrite stored answers. */
export function formatAnswerMarkdown(answer: string): string {
  if (/```|~~~/.test(answer)) return answer;
  answer = answer.replace(/^\*\*(已核实事实|待确认状态|需核实事项（建议）|需核实事项|核查结论|结论|建议)[：:]?\*\*[ \t]*[：:]?[ \t]*/gm, "$1：");
  answer = answer.replace(/^【([^【】\n]{1,40})】[ \t]*/gm, "#### $1\n\n");
  return answer
    .split(/\n\s*\n/)
    .map((block) => {
      // Preserve authored Markdown (including lists, tables, code and inline emphasis).
      if (/[\n#*`>|\[\]]/.test(block) || /^\s*([-+] |\d+[.)、])/.test(block))
        return block;
      const label = block.match(
        /^(结论|核查结论|已核实事实|待确认状态|需核实事项（建议）|需核实事项|已核实|本轮核实|待确认|待确认项|待核实|待核实项|依据|制度依据|建议|建议行动|下一步|以下为建议，非制度要求)[：:]/,
      );
      const content = label ? block.slice(label[0].length).trimStart() : block;
      if (label && /建议|下一步|已核实事实/.test(label[1]) && content.includes("；")) {
        return (
          `#### ${label[1]}\n\n` +
          content
            .split(/(?<=；)/)
            .filter(Boolean)
            .map((item) => `- ${item}`)
            .join("\n")
        );
      }
      const sentences = content.split(/(?<=。)/);
      const paragraphs: string[] = [];
      let current = "";
      for (const sentence of sentences) {
        if (current.length >= 100 && current.length + sentence.length > 170) {
          paragraphs.push(current);
          current = "";
        }
        current += sentence;
      }
      if (current) paragraphs.push(current);
      return (label ? `#### ${label[1]}\n\n` : "") + paragraphs.join("\n\n");
    })
    .join("\n\n");
}
