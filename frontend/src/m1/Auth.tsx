import { useState } from "react";
import { Alert, Button, Form, Input } from "antd";
import { IconArrowRight, IconBook2, IconDatabase, IconShieldCheck, IconSparkles } from "@tabler/icons-react";
import { api } from "./api";
import type { MeView } from "./types";
import { message, route } from "./ui";
import { Brand } from "./Brand";

export function Auth({
  register,
  onSuccess,
}: {
  register: boolean;
  onSuccess: (me: MeView) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(values: {
    email: string;
    password: string;
    display_name?: string;
  }) {
    setBusy(true);
    setError("");
    try {
      onSuccess(
        await api<MeView>(register ? "/registrations" : "/sessions", {
          method: "POST",
          body: values,
        }),
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <header>
        <Brand />
        <span className="auth-header-note">库存 · 知识 · AI 核查</span>
      </header>
      <main className="auth-layout">
        <section className="auth-copy">
          <div className="auth-intro">
            <span className="auth-kicker">
              <IconSparkles size={16} aria-hidden="true" /> 有据可循的运营决策
            </span>
            <h1>
              把核查的每一步，
              <br />
              <span>连接起来。</span>
            </h1>
            <p>
              库存、制度与 AI 分析，在一个工作空间协同。
              <br />
              知道数量，也知道结论从哪里来。
            </p>
          </div>
          <div className="auth-steps">
            {[
              [IconDatabase, "查询库存事实", "库存、批次与消耗，放在一起核实"],
              [IconBook2, "找到有效依据", "关联制度原文，让结论有出处"],
              [IconShieldCheck, "保留核查记录", "从发现问题，到跟进每一个待办"],
            ].map(([Icon, label, detail]) => {
              const Glyph = Icon as typeof IconDatabase;
              return (
                <div key={String(label)}>
                  <span className="auth-step-icon">
                    <Glyph size={20} aria-hidden="true" />
                  </span>
                  <div>
                    <strong>{String(label)}</strong>
                    <span>{String(detail)}</span>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="auth-copy-foot">
            事实清晰 <span aria-hidden="true">/</span> 依据可查{" "}
            <span aria-hidden="true">/</span> 行动可追溯
          </div>
        </section>
        <section className="auth-form" aria-labelledby="auth-heading">
          <div className="auth-form-heading">
            <h2 id="auth-heading">{register ? "创建账号" : "欢迎回来"}</h2>
            <p className="secondary-text">
              {register
                ? "一个账号，开始有据可循的库存核查。"
                : "继续核查库存，让下一步更清晰。"}
            </p>
          </div>
          <Form
            name={register ? "register" : "login"}
            layout="vertical"
            onFinish={submit}
            requiredMark={false}
            autoComplete="on"
            disabled={busy}
            scrollToFirstError={{ focus: true }}
          >
            {register && (
              <Form.Item
                name="display_name"
                label="姓名"
                rules={[
                  { required: true, whitespace: true, message: "请输入姓名" },
                  { max: 50, message: "姓名最多50字" },
                ]}
              >
                <Input
                  autoComplete="name"
                  maxLength={50}
                  placeholder="请输入你的姓名"
                />
              </Form.Item>
            )}
            <Form.Item
              name="email"
              label="邮箱"
              rules={[
                { required: true, message: "请输入邮箱" },
                { type: "email", message: "邮箱格式不正确" },
              ]}
            >
              <Input
                autoComplete="username"
                inputMode="email"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={254}
                placeholder="name@company.com"
              />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              extra={
                register
                  ? "至少 10 个字符，建议组合使用字母、数字和符号"
                  : undefined
              }
              rules={[
                { required: true, message: "请输入密码" },
                { min: 10, message: "密码至少10个字符" },
                { max: 128, message: "密码最多128个字符" },
              ]}
            >
              <Input.Password
                autoComplete={register ? "new-password" : "current-password"}
                maxLength={128}
                placeholder={register ? "设置你的登录密码" : "请输入登录密码"}
              />
            </Form.Item>
            {error && (
              <Alert
                type="error"
                showIcon
                title={error}
                className="page-alert"
              />
            )}
            <Button block type="primary" htmlType="submit" loading={busy}>
              {register ? "创建账号并进入" : "登录工作台"}
              <IconArrowRight size={16} />
            </Button>
          </Form>
          <div className="auth-privacy">
            <IconShieldCheck size={15} aria-hidden="true" />
            <span>
              {register
                ? "注册后将创建你的独立项目空间"
                : "项目权限隔离，核查记录留痕"}
            </span>
          </div>
          <p className="auth-switch">
            {register ? "已有账号？" : "还没有账号？"}
            <Button
              type="link"
              disabled={busy}
              onClick={() => route(register ? "/login" : "/register")}
            >
              {register ? "前往登录" : "注册账号"}
            </Button>
          </p>
        </section>
      </main>
      <footer>
        SPD 运营助手 <span aria-hidden="true">·</span> 让每一次核查有据可循
      </footer>
    </div>
  );
}

