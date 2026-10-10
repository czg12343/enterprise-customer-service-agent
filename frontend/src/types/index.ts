export interface User {
  id: string
  username: string
  email: string
  role: 'customer' | 'service' | 'admin'
  is_active: boolean
  created_at: string
}

export interface Product {
  id: string
  sku: string
  name: string
  category: string
  description: string
  price: number
  stock: number
  locked_stock: number
  is_active: boolean
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  status: string
  created_at: string
  updated_at: string
  refund_state?: { awaiting?: string; order_no?: string }
}

export interface Source {
  document: string
  page?: number
  section?: string
  snippet: string
  score: number
  citation_id?: number
  document_id?: string
  chunk_id?: string
}

export interface ToolCall {
  name: string
  arguments: Record<string, unknown>
  status: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  intent?: string
  sources: Source[]
  tool_calls: ToolCall[]
  feedback?: number
  created_at: string
  streaming?: boolean
}

export interface HandoffConversation {
  id: string
  title: string
  status: 'waiting_human' | 'human_active'
  customer_name: string
  assignee_id?: string
  latest_message: string
  updated_at: string
}

export interface OrderItem {
  product_name: string
  quantity: number
  unit_price: number
}

export interface Order {
  id: string
  order_no: string
  customer_username: string
  status: string
  payment_status: string
  shipping_status: string
  total_amount: number
  created_at: string
  items: OrderItem[]
  logistics?: {
    carrier: string
    tracking_no: string
    status: string
    latest_event: string
    estimated_delivery?: string
    delivered_at?: string | null
  }
}

export type TicketCategory = 'product' | 'order' | 'logistics' | 'refund' | 'repair' | 'complaint' | 'other'
export type TicketPriority = 'low' | 'normal' | 'high' | 'urgent'
export type TicketStatus = 'pending' | 'processing' | 'waiting_customer' | 'resolved' | 'closed'

export interface Ticket {
  id: string
  ticket_no: string
  user_id: string
  order_no?: string
  category: TicketCategory
  title: string
  description: string
  priority: TicketPriority
  status: TicketStatus
  assignee_id?: string
  result?: string
  created_at: string
  updated_at: string
}
