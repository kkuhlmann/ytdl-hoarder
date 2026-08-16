"use client"

import { useState, Dispatch, SetStateAction } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { MagnifyingGlassIcon, PlusIcon, ChevronDownIcon } from "@heroicons/react/20/solid"
import { TablePagination } from "@/app/_components/TablePagination"
import { SubscriptionsTable } from "@/app/_components/SubscriptionsTable"
import {
  SubscriptionOptionsType,
  SubscriptionType,
} from "../types/SubscriptionsOptions"
import { AddSubscriptionButton } from "@/app/_components/AddSubscriptionButton"
import { motion, AnimatePresence } from "framer-motion"

type SubscriptionsCardProps = {
  options: SubscriptionOptionsType
  setOptions: Dispatch<SetStateAction<SubscriptionOptionsType>>
  fetchData: (search: string | null, pageNumber: number) => Promise<any>
  subscriptions: SubscriptionType[]
  setSubscriptions: Dispatch<SetStateAction<SubscriptionType[]>>
  subscriptionSearch: string
  setSubscriptionSearch: Dispatch<SetStateAction<string>>
}

export function SubscriptionsCard({
  options,
  setOptions,
  fetchData,
  subscriptions,
  setSubscriptions,
  subscriptionSearch,
  setSubscriptionSearch,
}: SubscriptionsCardProps) {
  const [pageCount, setPageCount] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [showAddForm, setShowAddForm] = useState(false)

  const handleInputChange = (event: { target: { value: string } }) => {
    setSubscriptionSearch(event.target.value)
    setPageNumber(1)
  }

  const { isLoading: loading } = useFetchEffect(
    () =>
      fetchData(subscriptionSearch, pageNumber)
        .then(({ pageCount, tableRows }) => {
          setPageCount(pageCount)
          setSubscriptions(tableRows)
        })
        .catch(() => {}),
    [pageNumber, subscriptionSearch, fetchData, setSubscriptions],
    { enabled: subscriptionSearch.length === 0 || subscriptionSearch.length >= 3 }
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-4"
    >
      <div className="md:hidden">
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-mono transition-colors bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
        >
          <PlusIcon className="h-3.5 w-3.5" />
          New Subscription
          <ChevronDownIcon className={`h-3.5 w-3.5 transition-transform ${showAddForm ? "rotate-180" : ""}`} />
        </button>
        <AnimatePresence>
          {showAddForm && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="pt-2">
                <AddSubscriptionButton
                  options={options}
                  setOptions={setOptions}
                  fetchSubscriptions={fetchData}
                  setSubscriptions={setSubscriptions}
                  setPageCount={setPageCount}
                  pageNumber={pageNumber}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="hidden md:block">
        <AddSubscriptionButton
          options={options}
          setOptions={setOptions}
          fetchSubscriptions={fetchData}
          setSubscriptions={setSubscriptions}
          setPageCount={setPageCount}
          pageNumber={pageNumber}
        />
      </div>

      <Card>
        <CardContent className="space-y-4 pt-4 md:pt-6">
          <div className="relative">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
            <Input
              placeholder="Search subscriptions..."
              value={subscriptionSearch}
              onChange={handleInputChange}
              className="pl-9"
            />
          </div>

          <div className="md:rounded-lg md:border md:border-border overflow-hidden">
            <SubscriptionsTable
              subscriptions={subscriptions}
              loading={loading}
              fetchSubscriptions={fetchData}
              setSubscriptions={setSubscriptions}
            />
          </div>

          <TablePagination
            pageNumber={pageNumber}
            pageCount={pageCount}
            setPageNumber={setPageNumber}
          />
        </CardContent>
      </Card>
    </motion.div>
  )
}
